# Volatility
# Copyright (c) 2008-2011 Volatile Systems
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

"""
@author:       Bradley L Schatz
@license:      GNU General Public License 2.0 or later
@contact:      bradley@schatzforensic.com.au

This file provides support for windows Windows 7 SP 0.
"""

#pylint: disable-msg=C0111

import volatility.obj as obj
import copy
import win7_sp0_x86_vtypes
import win7_sp0_x86_syscalls
import vista_sp0_x86
import windows
import crash_vtypes
import hibernate_vtypes
import kdbg_vtypes
import tcpip_vtypes
import volatility.debug as debug #pylint: disable-msg=W0611

win7sp0x86overlays = copy.deepcopy(vista_sp0_x86.vistasp0x86overlays)

# Remove the _OBJECT_HEADER overlays since win7 handles them differently.
win7sp0x86overlays.pop("_OBJECT_HEADER", 0)

win7sp0x86overlays['VOLATILITY_MAGIC'][1]['DTBSignature'][1] = ['VolatilityMagic', dict(value = "\x03\x00\x26\x00")]
win7sp0x86overlays['VOLATILITY_MAGIC'][1]['KPCR'][1] = ['VolatilityKPCR', dict(configname = 'KPCR')]
win7sp0x86overlays['VOLATILITY_MAGIC'][1]['KDBGHeader'][1] = ['VolatilityMagic', dict(value = '\x00\x00\x00\x00\x00\x00\x00\x00KDBG\x40\x03')]
win7sp0x86overlays['VOLATILITY_MAGIC'][1]['HiveListOffset'][1] = ['VolatilityMagic', dict(value = 0x30c)]
win7sp0x86overlays['VOLATILITY_MAGIC'][1]['HiveListPoolSize'][1] = ['VolatilityMagic', dict(value = 0x638)]

# Add a new member to the VOLATILIY_MAGIC type
win7sp0x86overlays['VOLATILITY_MAGIC'][1]['ObjectPreamble'] = [ 0x0, ['VolatilityMagic', dict(value = '_OBJECT_HEADER_CREATOR_INFO')]]


win7sp0x86overlays['VOLATILITY_MAGIC'][1]['TypeIndexMap'] = [ 0x0, ['VolatilityMagic', \
      dict(value = { 2: 'Type',
            3: 'Directory',
            4: 'SymbolicLink',
            5: 'Token',
            6: 'Job',
            7: 'Process',
            8: 'Thread',
            9: 'UserApcReserve',
            10: 'IoCompletionReserve',
            11: 'DebugObject',
            12: 'Event',
            13: 'EventPair',
            14: 'Mutant',
            15: 'Callback',
            16: 'Semaphore',
            17: 'Timer',
            18: 'Profile',
            19: 'KeyedEvent',
            20: 'WindowStation',
            21: 'Desktop',
            22: 'TpWorkerFactory',
            23: 'Adapter',
            24: 'Controller',
            25: 'Device',
            26: 'Driver',
            27: 'IoCompletion',
            28: 'File',
            29: 'TmTm',
            30: 'TmTx',
            31: 'TmRm',
            32: 'TmEn',
            33: 'Section',
            34: 'Session',
            35: 'Key',
            36: 'ALPC Port',
            37: 'PowerRequest',
            38: 'WmiGuid',
            39: 'EtwRegistration',
            40: 'EtwConsumer',
            41: 'FilterConnectionPort',
            42: 'FilterCommunicationPort',
            43: 'PcwObject',
            })]]

win7_sp0_x86_vtypes.nt_types.update(crash_vtypes.crash_vtypes)
win7_sp0_x86_vtypes.nt_types.update(hibernate_vtypes.hibernate_vtypes)
win7_sp0_x86_vtypes.nt_types.update(kdbg_vtypes.kdbg_vtypes)
win7_sp0_x86_vtypes.nt_types.update(tcpip_vtypes.tcpip_vtypes)
win7_sp0_x86_vtypes.nt_types.update(tcpip_vtypes.tcpip_vtypes_vista)
win7_sp0_x86_vtypes.nt_types.update(tcpip_vtypes.tcpip_vtypes_7)

win7_object_classes = copy.deepcopy(vista_sp0_x86.VistaSP0x86.object_classes)


class _OBJECT_HEADER(windows._OBJECT_HEADER):
    """A Volatility object to handle Windows 7 object headers.

    Windows 7 changes the way objects are handled:
    References: http://www.codemachine.com/article_objectheader.html
    """

    def __init__(self, *args, **kwargs):
        # kernel AS for dereferencing pointers 
        self.kas = None
        super(_OBJECT_HEADER, self).__init__(*args, **kwargs)

        # Create accessors for optional headers
        self.find_optional_headers()

    # This specifies the order the headers are found below the _OBJECT_HEADER
    optional_header_mask = (('_OBJECT_HEADER_CREATOR_INFO', 0x01),
                            ('_OBJECT_HEADER_NAME_INFO', 0x02),
                            ('_OBJECT_HEADER_HANDLE_INFO', 0x04),
                            ('_OBJECT_HEADER_QUOTA_INFO', 0x08),
                            ('_OBJECT_HEADER_PROCESS_INFO', 0x10))

    def find_optional_headers(self):
        """Find this object's optional headers."""
        offset = self.obj_offset
        info_mask = int(self.InfoMask)

        for name, mask in self.optional_header_mask:
            if info_mask & mask:
                offset -= self.obj_vm.profile.get_obj_size(name)
                o = obj.Object(name, offset, vm=self.obj_vm, native_vm=self.obj_native_vm)
            else:
                o = obj.NoneObject("Header not set")

            self.newattr(name, o)

    def get_object_type(self):
        """Return the object's type as a string"""
        volmagic = obj.Object("VOLATILITY_MAGIC", 0x0, self.obj_vm)
        type_map = volmagic.TypeIndexMap.v()

        return type_map.get(self.TypeIndex.v(), '')


# Update the win7 implementation
win7_object_classes["_OBJECT_HEADER"] = _OBJECT_HEADER

class Win7SP0x86(windows.AbstractWindows):
    """ A Profile for Windows 7 SP0 x86 """
    _md_major = 6
    _md_minor = 1
    abstract_types = win7_sp0_x86_vtypes.nt_types
    overlay = win7sp0x86overlays
    object_classes = win7_object_classes
    syscalls = win7_sp0_x86_syscalls.syscalls
    # FIXME: Temporary fix for issue 105
    native_types = copy.deepcopy(windows.AbstractWindows.native_types)
    native_types['pointer64'] = windows.AbstractWindows.native_types['unsigned long long']