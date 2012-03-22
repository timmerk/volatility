# Volatility
#
# Authors:
# Michael Cohen <scudette@users.sourceforge.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details. 
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA 
#

""" This plugin contains CORE classes used by lots of other plugins """
import logging

from volatility import scan
from volatility import obj
from volatility import commands
from volatility import profile
from volatility import plugin

#pylint: disable-msg=C0111

# We require both a physical AS set and a valid profile for
# AbstractWindowsCommandPlugins.

class AbstractWindowsCommandPlugin(plugin.PhysicalASMixin,
                                   plugin.ProfileCommand):
    """A base class for all windows based plugins.

    Windows based plugins require at a minimum a working profile, and a valid
    physical address space.
    """

    __abstract = True

    @classmethod
    def is_active(cls, config):
        """We are only active if the profile is windows."""
        return (getattr(config.profile, "_md_os", None) == 'windows' and
                plugin.Command.is_active(config))


# TODO: remove this when all the plugins have been switched over..
class AbstractWindowsCommand(commands.command):
    """A base class for all windows based plugins."""

    @classmethod
    def is_active(cls, config):
        """We are only active if the profile is windows."""
        return (getattr(config.profile, "_md_os", None) == 'windows' and
                plugin.Command.is_active(config))


class WinFindDTB(AbstractWindowsCommandPlugin):
    """A plugin to search for the Directory Table Base for windows systems.

    There are a number of ways to find the DTB:

    - Scanner method: Scans the image for a known kernel process, and read the
      DTB from its Process Environment Block (PEB).

    - Get the DTB from the KPCR structure.
    """

    __name = "find_dtb"

    # We scan this many bytes at once
    SCAN_BLOCKSIZE = 1024 * 1024

    def __init__(self, process_name = "Idle", **kwargs):
        """Scans the image for the Idle process.

        Args:
          process_name: The name of the process we should look for. (If we are
            looking for the kernel DTB, any kernel process will do here.)

          physical_address_space: The address space to search. If None, we use
            the session's physical_address_space.

          profile: An optional profile to use (or we use the session's).
        """
        super(WinFindDTB, self).__init__(**kwargs)

        self.process_name = process_name

        # This is the offset from the ImageFileName member to the start of the
        # _EPROCESS
        self.image_name_offset = self.profile.get_obj_offset(
            "_EPROCESS", "ImageFileName")

    def scan_for_process(self):
        """Scan the image for the idle process."""
        needle = self.process_name + "\x00" * (16 - len(self.process_name))
        offset = 0
        while 1:
            data = self.physical_address_space.read(offset, self.SCAN_BLOCKSIZE)
            found = 0
            if not data:
                break

            while 1:
                found = data.find(needle, found + 1)
                if found >= 0:
                    # We found something that looks like the process we want.
                    self.eprocess = self.profile.Object(
                        "_EPROCESS", offset = offset + found - self.image_name_offset,
                        vm = self.physical_address_space)

                    yield self.eprocess
                else:
                    break

            offset += len(data)

    def dtb_hits(self):
        for x in self.scan_for_process():
            result = x.Pcb.DirectoryTableBase.v()
            yield result

    def verify_address_space(self, address_space):
        """Check the eprocess for sanity."""
        # Reflect through the address space at ourselves. Note that the Idle
        # process is not usually in the PsActiveProcessHead list, so we use the
        # ThreadListHead instead.
        list_head = self.eprocess.ThreadListHead.Flink

        me = list_head.dereference(vm=address_space).Blink.dereference()
        if me.v() != list_head.v():
            raise AssertionError("Unable to reflect _EPROCESS through this address space.")

        return True

    def render(self, fd = None):
        fd.write("_EPROCESS (P)   DTB\n")
        for eprocess in self.scan_for_process():
            dtb = eprocess.Pcb.DirectoryTableBase.v()
                    
            fd.write("{0:#010x}  {1:#010x}\n".format(eprocess.obj_offset, dtb))


## The following are checks for pool scanners.

class PoolTagCheck(scan.ScannerCheck):
    """ This scanner checks for the occurance of a pool tag """
    def __init__(self, tag = None, tags = None, **kwargs):
        super(PoolTagCheck, self).__init__(**kwargs)
        self.tags = tags or [tag]

    def skip(self, data, offset):
        nextvals = []
        for tag in self.tags:
            nextval = data.find(tag, offset + 1)
            if nextval >= 0:
                nextvals.append(nextval)

        # No tag was found
        if not nextvals:
            # Substrings are not found - skip to the end of this data buffer
            return len(data) - offset

        return min(nextvals) - offset

    def check(self, offset):
        for tag in self.tags:
            data = self.address_space.read(offset, len(tag))
            if data == tag:
                return True


class CheckPoolSize(scan.ScannerCheck):
    """ Check pool block size """
    def __init__(self, condition = (lambda x: x == 8), **kwargs):
        super(CheckPoolSize, self).__init__(**kwargs)
        self.condition = condition
        self.pool_align = self.profile.constants['PoolAlignment']

    def check(self, offset):
        pool_hdr = self.profile.Object('_POOL_HEADER', vm = self.address_space,
                                       offset = offset - 4)
        block_size = pool_hdr.BlockSize.v()

        return self.condition(block_size * self.pool_align)


class CheckPoolType(scan.ScannerCheck):
    """ Check the pool type """
    def __init__(self, paged=False, non_paged=False, free=False, **kwargs):
        super(CheckPoolType, self).__init__(**kwargs)
        self.non_paged = non_paged
        self.paged = paged
        self.free = free

    def check(self, offset):
        pool_hdr = self.profile.Object('_POOL_HEADER', vm = self.address_space,
                                       offset = offset - 4)

        ptype = pool_hdr.PoolType.v()

        if self.non_paged and (ptype % 2) == 1:
            return True

        if self.free and ptype == 0:
            return True

        if self.paged and (ptype % 2) == 0 and ptype > 0:
            return True


class CheckPoolIndex(scan.ScannerCheck):
    """ Checks the pool index """
    def __init__(self, value = 0, **kwargs):
        super(CheckPoolIndex, self).__init__(**kwargs)
        self.value = value

    def check(self, offset):
        pool_hdr = self.profile.Object('_POOL_HEADER', vm = self.address_space,
                                       offset = offset - 4)

        return pool_hdr.PoolIndex == self.value


class PoolScannerPlugin(plugin.KernelASMixin, AbstractWindowsCommandPlugin):
    """A base class for all pool scanner plugins."""
    __abstract = True 


class KDBGMixin(plugin.KernelASMixin):
    """A plugin mixin to make sure the kdbg is set correctly."""

    def __init__(self, kdbg=None, **kwargs):
        """Ensure there is a valid KDBG object.

        Args:
          kdbg: The location of the kernel debugger block (In the physical
             AS).
        """
        super(KDBGMixin, self).__init__(**kwargs)
        self.kdbg = kdbg or self.session.kdbg
        if self.kdbg is None:
            logging.info("KDBG not provided - Volatility will try to "
                         "automatically scan for it now using plugin.kdbgscan.")
            for kdbg in self.session.plugins.kdbgscan(session=self.session).hits():
                # Just return the first one
                logging.info("Found a KDBG hit %r. Hope it works. If not try "
                             "setting it manually.", kdbg)

                # Cache this for next time in the session.
                self.session.kdbg = self.kdbg = kdbg
                break

        # Allow kdbg to be an actual object.
        if isinstance(self.kdbg, obj.BaseObject):
            return
        # Or maybe its an integer representing the offset.
        elif self.kdbg:
            self.kdbg = self.profile.Object(
                theType="_KDDEBUGGER_DATA64", offset=int(self.kdbg),
                vm=self.kernel_address_space)
        else:
            self.kdbg = obj.NoneObject("Could not guess kdbg offset")


class WinProcessFilter(KDBGMixin, AbstractWindowsCommandPlugin):
    """A class for filtering processes."""

    __abstract = True

    def __init__(self, phys_eprocess=None, pids=None, pid=None, **kwargs):
        """Lists information about all the dlls mapped by a process.
        
        Args:
           physical_eprocess: One or more EPROCESS structs or offsets defined in
              the physical AS.
           
           pids: A list of pids.
           pid: A single pid.
        """
        super(WinProcessFilter, self).__init__(**kwargs)

        if isinstance(phys_eprocess, int):
            phys_eprocess = [phys_eprocess]
        elif phys_eprocess is None:
            phys_eprocess = []

        self.phys_eprocess = phys_eprocess

        if pids is None:
            pids = []

        if pid is not None:
            pids.append(pid)

        self.pids = pids

    def filter_processes(self):
        """Filters eprocess list using phys_eprocess and pids lists."""
        # No filtering required:
        if not self.phys_eprocess and not self.pids:
            for eprocess in self.session.plugins.pslist(
                session=self.session, kdbg=self.kdbg).list_eprocess():
                yield eprocess
        else:
            # We need to filter by phys_eprocess
            for offset in self.phys_eprocess:
                yield self.virtual_process_from_physical_offset(offset)

            # We need to filter by pids
            for eprocess in self.session.plugins.pslist(
                session=self.session, kdbg=self.kdbg).list_eprocess():
                if int(eprocess.UniqueProcessId) in self.pids:
                    yield eprocess

    def virtual_process_from_physical_offset(self, physical_offset):
        """Tries to return an eprocess in virtual space from a physical offset.

        We do this by reflecting off the list elements.

        Args:
           physical_offset: The physcial offset of the process.

        Returns:
           an _EPROCESS object or a NoneObject on failure.
        """
        physical_eprocess = self.profile.Object(
            theType="_EPROCESS", offset=int(physical_offset),
            vm=self.kernel_address_space.base)

        # We cast our list entry in the kernel AS by following Flink into the
        # kernel AS and then the Blink. Note the address space switch upon
        # dereferencing the pointer.
        our_list_entry = physical_eprocess.ActiveProcessLinks.Flink.dereference(
            vm=self.kernel_address_space).Blink.dereference()

        # Now we get the EPROCESS object from the list entry.
        return our_list_entry.dereference_as("_EPROCESS", "ActiveProcessLinks")

