#!/usr/bin/env python
#
#       fileobjscan.py
#       Copyright 2009 Andreas Schuster <a.schuster@yendor.net>
#       Copyright (C) 2009-2011 Volatile Systems
#       
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#       
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#       
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

"""
@author:       Andreas Schuster
@license:      GNU General Public License 2.0 or later
@contact:      a.schuster@forensikblog.de
@organization: http://computer.forensikblog.de/en/
"""

import volatility.scan as scan
import volatility.commands as commands
import volatility.debug as debug #pylint: disable-msg=W0611
import volatility.utils as utils
import volatility.obj as obj

class PoolScanFile(scan.PoolScanner):
    """PoolScanner for File objects"""
    ## We dont want any preamble - the offsets should be those of the
    ## _POOL_HEADER directly.
    preamble = []
    checks = [ ('PoolTagCheck', dict(tag = "Fil\xe5")),
               ('CheckPoolSize', dict(condition = lambda x: x >= 0x98)),
               ('CheckPoolType', dict(paged = True, non_paged = True, free = True)),
               ('CheckPoolIndex', dict(value = 0)),
               ]

class FileScan(commands.command):
    """ Scan Physical memory for _FILE_OBJECT pool allocations
    """
    # Declare meta information associated with this plugin
    meta_info = {}
    meta_info['author'] = 'Andreas Schuster'
    meta_info['copyright'] = 'Copyright (c) 2009 Andreas Schuster'
    meta_info['contact'] = 'a.schuster@forensikblog.de'
    meta_info['license'] = 'GNU General Public License 2.0 or later'
    meta_info['url'] = 'http://computer.forensikblog.de/en/'
    meta_info['os'] = 'WIN_32_XP_SP2'
    meta_info['version'] = '0.1'

    def __init__(self, config, *args):
        commands.command.__init__(self, config, *args)
        self.kernel_address_space = None

    def parse_string(self, unicode_obj):
        """Unicode string parser"""
        ## We need to do this because the unicode_obj buffer is in
        ## kernel_address_space
        string_length = unicode_obj.Length
        string_offset = unicode_obj.Buffer

        string = self.kernel_address_space.read(string_offset, string_length)
        if not string:
            return ''
        return repr(string[:255].decode("utf16", "ignore").encode("utf8", "xmlcharrefreplace"))

    # Can't be cached until self.kernel_address_space is moved entirely within calculate
    def calculate(self):
        ## Just grab the AS and scan it using our scanner
        address_space = utils.load_as(self._config, astype = 'physical')

        ## Will need the kernel AS for later:
        self.kernel_address_space = utils.load_as(self._config)

        for offset in PoolScanFile().scan(address_space):

            pool_obj = obj.Object("_POOL_HEADER", vm = address_space,
                                 offset = offset)

            ## We work out the _FILE_OBJECT from the end of the
            ## allocation (bottom up).
            file_obj = obj.Object("_FILE_OBJECT", vm = address_space,
                                 offset = offset + pool_obj.BlockSize * 8 - \
                                 address_space.profile.get_obj_size("_FILE_OBJECT")
                                 )

            ## The _OBJECT_HEADER is immediately below the _FILE_OBJECT
            object_obj = obj.Object("_OBJECT_HEADER", vm = address_space,
                                   offset = file_obj.obj_offset - \
                                   address_space.profile.get_obj_offset('_OBJECT_HEADER', 'Body')
                                   )

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, address_space)
            try:
                # New object header
                if object_obj.TypeIndex != volmagic.TypeIndexMap.v()['File']:
                    continue
            except AttributeError:
                # Default to old Object header
                # Skip unallocated objects
                #if object_obj.Type == 0xbad0b0b0:
                #    continue
                pass

            ## If the string is not reachable we skip it
            Name = self.parse_string(file_obj.FileName)
            if not Name:
                continue

            yield (object_obj, file_obj, Name)

    def render_text(self, outfd, data):
        outfd.write("{0:10} {1:10} {2:4} {3:4} {4:6} {5}\n".format(
                     'Phys.Addr.', 'Obj Type', '#Ptr', '#Hnd', 'Access', 'Name'))

        for object_obj, file_obj, Name in data:
            ## Make a nicely formatted ACL string
            AccessStr = ((file_obj.ReadAccess > 0 and "R") or '-') + \
                        ((file_obj.WriteAccess > 0  and "W") or '-') + \
                        ((file_obj.DeleteAccess > 0 and "D") or '-') + \
                        ((file_obj.SharedRead > 0 and "r") or '-') + \
                        ((file_obj.SharedWrite > 0 and "w") or '-') + \
                        ((file_obj.SharedDelete > 0 and "d") or '-')

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, self.kernel_address_space)
            try:
                # New object header
                info_mask_to_offset = volmagic.InfoMaskToOffset.v()
                type_info = object_obj.TypeIndex
            except AttributeError:
                # Default to old Object header
                type_info = object_obj.Type

            outfd.write("0x{0:08x} 0x{1:08x} {2:4} {3:4} {4:6} {5}\n".format(
                         object_obj.obj_offset, type_info, object_obj.PointerCount,
                         object_obj.HandleCount, AccessStr, Name))

class PoolScanDriver(PoolScanFile):
    """ Scanner for _DRIVER_OBJECT """
    ## No preamble
    checks = [ ('PoolTagCheck', dict(tag = "Dri\xf6")),
               ('CheckPoolSize', dict(condition = lambda x: x >= 0xf8)),
               ('CheckPoolType', dict(paged = True, non_paged = True, free = True)),
               ('CheckPoolIndex', dict(value = 0)),
               ]

class DriverScan(FileScan):
    "Scan for driver objects _DRIVER_OBJECT "
    def calculate(self):
        ## Just grab the AS and scan it using our scanner
        address_space = utils.load_as(self._config, astype = 'physical')

        ## Will need the kernel AS for later:
        self.kernel_address_space = utils.load_as(self._config)

        for offset in PoolScanDriver().scan(address_space):
            pool_obj = obj.Object("_POOL_HEADER", vm = address_space,
                                 offset = offset)

            ## We work out the _DRIVER_OBJECT from the end of the
            ## allocation (bottom up).
            extension_obj = obj.Object(
                "_DRIVER_EXTENSION", vm = address_space,
                offset = offset + pool_obj.BlockSize * 8 - 4 - \
                address_space.profile.get_obj_size("_DRIVER_EXTENSION"))

            ## The _DRIVER_OBJECT is immediately below the _DRIVER_EXTENSION
            driver_obj = obj.Object(
                "_DRIVER_OBJECT", vm = address_space,
                offset = extension_obj.obj_offset - \
                address_space.profile.get_obj_size("_DRIVER_OBJECT")
                )

            ## The _OBJECT_HEADER is immediately below the _DRIVER_OBJECT
            object_obj = obj.Object(
                "_OBJECT_HEADER", vm = address_space,
                offset = driver_obj.obj_offset - \
                address_space.profile.get_obj_offset('_OBJECT_HEADER', 'Body')
                )

            ## Skip unallocated objects
            #if object_obj.Type == 0xbad0b0b0:
            #    continue

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, address_space)
            try:
                # New object header
                if object_obj.TypeIndex != volmagic.TypeIndexMap.v()['Driver']:
                    continue
                info_mask_to_offset = volmagic.InfoMaskToOffset.v()
                OBJECT_HEADER_NAME_INFO = \
                    volmagic.InfoMaskMap.v()['_OBJECT_HEADER_NAME_INFO']
                info_mask_to_offset_index = \
                    object_obj.InfoMask & \
                    (OBJECT_HEADER_NAME_INFO | (OBJECT_HEADER_NAME_INFO - 1))
                if info_mask_to_offset_index in info_mask_to_offset:
                    name_info_offset = \
                      info_mask_to_offset[info_mask_to_offset_index]
                else:
                    name_info_offset = 0
            except AttributeError:
                # Default to old Object header
                name_info_offset = object_obj.NameInfoOffset
                pass

            object_name_string = ""

            if name_info_offset:
                ## Now work out the OBJECT_HEADER_NAME_INFORMATION object
                object_name_info_obj = \
                    obj.Object("_OBJECT_HEADER_NAME_INFORMATION", \
                    vm = address_space, \
                    offset = object_obj.obj_offset - \
                    name_info_offset \
                    )
                object_name_string = self.parse_string(object_name_info_obj.Name)
            yield (object_obj, driver_obj, extension_obj, object_name_string)


    def render_text(self, outfd, data):
        """Renders the text-based output"""
        outfd.write("{0:10} {1:10} {2:4} {3:4} {4:10} {5:>6} {6:20} {7}\n".format(
                     'Phys.Addr.', 'Obj Type', '#Ptr', '#Hnd',
                     'Start', 'Size', 'Service key', 'Name'))

        for object_obj, driver_obj, extension_obj, ObjectNameString in data:

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, self.kernel_address_space)
            try:
                # New object header
                info_mask_to_offset = volmagic.InfoMaskToOffset.v()
                type_info = object_obj.TypeIndex
            except AttributeError:
                # Default to old Object header
                type_info = object_obj.Type

            outfd.write("0x{0:08x} 0x{1:08x} {2:4} {3:4} 0x{4:08x} {5:6} {6:20} {7:12} {8}\n".format(
                         driver_obj.obj_offset, type_info, object_obj.PointerCount,
                         object_obj.HandleCount,
                         driver_obj.DriverStart, driver_obj.DriverSize,
                         self.parse_string(extension_obj.ServiceKeyName),
                         ObjectNameString,
                         self.parse_string(driver_obj.DriverName)))

class PoolScanMutant(PoolScanDriver):
    """ Scanner for Mutants _KMUTANT """
    checks = [ ('PoolTagCheck', dict(tag = "Mut\xe1")),
               ('CheckPoolSize', dict(condition = lambda x: x >= 0x40)),
               ('CheckPoolType', dict(paged = True, non_paged = True, free = True)),
               ('CheckPoolIndex', dict(value = 0)),
               ]


class MutantScan(FileScan):
    "Scan for mutant objects _KMUTANT "
    def __init__(self, config, *args):
        FileScan.__init__(self, config, *args)
        config.add_option("SILENT", short_option = 's', default = False,
                          action = 'store_true', help = 'Suppress less meaningful results')

    def calculate(self):
        ## Just grab the AS and scan it using our scanner
        address_space = utils.load_as(self._config, astype = 'physical')

        ## Will need the kernel AS for later:
        self.kernel_address_space = utils.load_as(self._config)

        for offset in PoolScanMutant().scan(address_space):
            pool_obj = obj.Object("_POOL_HEADER", vm = address_space,
                                 offset = offset)

            ## We work out the _DRIVER_OBJECT from the end of the
            ## allocation (bottom up).
            mutant = obj.Object(
                "_KMUTANT", vm = address_space,
                offset = offset + pool_obj.BlockSize * 8 - \
                address_space.profile.get_obj_size("_KMUTANT"))

            ## The _OBJECT_HEADER is immediately below the _KMUTANT
            object_obj = obj.Object(
                "_OBJECT_HEADER", vm = address_space,
                offset = mutant.obj_offset - \
                address_space.profile.get_obj_offset('_OBJECT_HEADER', 'Body')
                )

            ## Skip unallocated objects
            ##if object_obj.Type == 0xbad0b0b0:
            ##   continue

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, address_space)
            try:
                # New object header
                if object_obj.TypeIndex != volmagic.TypeIndexMap.v()['Mutant']:
                    continue
                info_mask_to_offset = volmagic.InfoMaskToOffset.v()
                OBJECT_HEADER_NAME_INFO = \
                    volmagic.InfoMaskMap.v()['_OBJECT_HEADER_NAME_INFO']
                info_mask_to_offset_index = \
                    object_obj.InfoMask & \
                    (OBJECT_HEADER_NAME_INFO | (OBJECT_HEADER_NAME_INFO - 1))
                if info_mask_to_offset_index in info_mask_to_offset:
                    name_info_offset = \
                      info_mask_to_offset[info_mask_to_offset_index]
                else:
                    name_info_offset = 0
            except AttributeError:
                # Default to old Object header
                name_info_offset = object_obj.NameInfoOffset
                pass

            object_name_string = ""

            if name_info_offset:
                ## Now work out the OBJECT_HEADER_NAME_INFORMATION object
                object_name_info_obj = \
                    obj.Object("_OBJECT_HEADER_NAME_INFORMATION", \
                    vm = address_space, \
                    offset = object_obj.obj_offset - \
                    name_info_offset \
                    )
                object_name_string = self.parse_string(object_name_info_obj.Name)

            if self._config.SILENT:
                if name_info_offset == 0:
                    continue

            yield (object_obj, mutant, object_name_string)


    def render_text(self, outfd, data):
        """Renders the output"""
        outfd.write("{0:10} {1:10} {2:4} {3:4} {4:6} {5:10} {6:10} {7}\n".format(
                     'Phys.Addr.', 'Obj Type', '#Ptr', '#Hnd', 'Signal',
                     'Thread', 'CID', 'Name'))

        for object_obj, mutant, ObjectNameString in data:
            if mutant.OwnerThread > 0x80000000:
                thread = obj.Object("_ETHREAD", vm = self.kernel_address_space,
                                   offset = mutant.OwnerThread)
                CID = "{0}:{1}".format(thread.Cid.UniqueProcess, thread.Cid.UniqueThread)
            else:
                CID = ""

            ## Account for changes to the object header for Windows 7
            volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, self.kernel_address_space)
            try:
                # New object header
                info_mask_to_offset = volmagic.InfoMaskToOffset.v()
                type_info = object_obj.TypeIndex
            except AttributeError:
                # Default to old Object header
                type_info = object_obj.Type

            outfd.write("0x{0:08x} 0x{1:08x} {2:4} {3:4} {4:6} 0x{5:08x} {6:10} {7}\n".format(
                         mutant.obj_offset, type_info, object_obj.PointerCount,
                         object_obj.HandleCount, mutant.Header.SignalState,
                         mutant.OwnerThread, CID,
                         ObjectNameString
                         ))