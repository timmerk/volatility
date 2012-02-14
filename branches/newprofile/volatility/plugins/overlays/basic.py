# Volatility
#
# Authors:
# Michael Cohen <scudette@users.sourceforge.net>
# Mike Auty <mike.auty@gmail.com>
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

""" This file defines some basic types which might be useful for many
OS's
"""
import copy
import volatility.obj as obj
import volatility.debug as debug #pylint: disable-msg=W0611
import volatility.constants as constants
import volatility.plugins.overlays.native_types as native_types

class String(obj.NativeType):
    """Class for dealing with Strings"""
    def __init__(self, theType, offset, vm = None,
                 length = 1, parent = None, profile = None, **kwargs):
        ## Allow length to be a callable:
        if callable(length):
            length = length(parent)

        self.length = length

        ## length must be an integer
        obj.NativeType.__init__(self, theType, offset, vm, parent = parent, profile = profile,
                                format_string = "{0}s".format(length), **kwargs)

    def proxied(self, name):
        """ Return an object to be proxied """
        return self.__str__()

    def __str__(self):
        data = self.v()
        ## Make sure its null terminated:
        result = data.split("\x00")[0]
        if not result:
            return ""
        return result

    def __format__(self, formatspec):
        return format(self.__str__(), formatspec)

    def __add__(self, other):
        """Set up mappings for concat"""
        return str(self) + other

    def __radd__(self, other):
        """Set up mappings for reverse concat"""
        return other + str(self)

class Flags(obj.NativeType):
    """ This object decodes each flag into a string """
    ## This dictionary maps each bit to a String
    bitmap = None

    ## This dictionary maps a string mask name to a bit range
    ## consisting of a list of start, width bits
    maskmap = None

    def __init__(self, theType = None, offset = 0, vm = None, parent = None,
                 bitmap = None, maskmap = None, target = "unsigned long",
                 **kwargs):
        self.bitmap = bitmap or {}
        self.maskmap = maskmap or {}
        self.target = target

        self.target_obj = obj.Object(target, offset = offset, vm = vm, parent = parent)
        obj.NativeType.__init__(self, theType, offset, vm, parent, **kwargs)

    def v(self):
        return self.target_obj.v()

    def __str__(self):
        result = []
        value = self.v()
        keys = self.bitmap.keys()
        keys.sort()
        for k in keys:
            if value & (1 << self.bitmap[k]):
                result.append(k)

        return ', '.join(result)

    def __format__(self, formatspec):
        return format(self.__str__(), formatspec)

    def __getattr__(self, attr):
        maprange = self.maskmap.get(attr)
        if not maprange:
            return obj.NoneObject("Mask {0} not known".format(attr))

        bits = 2 ** maprange[1] - 1
        mask = bits << maprange[0]

        return self.v() & mask


class Enumeration(obj.NativeType):
    """Enumeration class for handling multiple possible meanings for a single value"""

    def __init__(self, theType = None, offset = 0, vm = None, parent = None,
                 choices = None, target = "unsigned long", **kwargs):
        self.choices = choices or {}
        self.target = target
        self.target_obj = obj.Object(target, offset = offset, vm = vm, parent = parent)
        obj.NativeType.__init__(self, theType, offset, vm, parent, **kwargs)

    def v(self):
        return self.target_obj.v()

    def __str__(self):
        value = self.v()
        if value in self.choices.keys():
            return self.choices[value]
        return 'Unknown choice ' + str(value)

    def __format__(self, formatspec):
        return format(self.__str__(), formatspec)


class VOLATILITY_MAGIC(obj.CType):
    """Class representing a VOLATILITY_MAGIC namespace
    
       Needed to ensure that the address space is not verified as valid for constants
    """
    def __init__(self, theType, offset, vm, **kwargs):
        try:
            obj.CType.__init__(self, theType, offset, vm, **kwargs)
        except obj.InvalidOffsetError:
            # The exception will be raised before this point,
            # so we must finish off the CType's __init__ ourselves
            self.__initialized = True


class VolatilityDTB(obj.VolatilityMagic):

    def generate_suggestions(self):
        offset = 0
        while 1:
            data = self.obj_vm.read(offset, constants.SCAN_BLOCKSIZE)
            found = 0
            if not data:
                break

            while 1:
                found = data.find(str(self.obj_parent.DTBSignature), found + 1)
                if found >= 0:
                    # (_type, _size) = unpack('=HH', data[found:found+4])
                    proc = obj.Object("_EPROCESS", offset = offset + found,
                                      vm = self.obj_vm)
                    if 'Idle' in proc.ImageFileName.v():
                        yield proc.Pcb.DirectoryTableBase.v()
                else:
                    break

            offset += len(data)


class BasicObjectClasses(obj.Hook):

    def modification(self, profile):
        profile.object_classes.update({
            'String': String,
            'Flags': Flags,
            'Enumeration': Enumeration,
            'VOLATILITY_MAGIC': VOLATILITY_MAGIC,
            'VolatilityDTB': VolatilityDTB,
            })


### DEPRECATED FEATURES ###
#
# These are due from removal after version 2.2,
# please do not rely upon them

x86_native_types_32bit = native_types.x86_native_types
x86_native_types_64bit = native_types.x64_native_types
