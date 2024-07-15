from mmap import mmap
from typing import Tuple, Union, Any, List
from struct import Struct

BufferType = Union[List[int], bytes, bytearray, memoryview, mmap]

class BaseStruct():
    @property
    def size(self):
        # type: () -> int
        raise NotImplementedError()
    
    def unpack_from(self, buffer, offset=0):
        # type: (BufferType, int) -> Any
        raise NotImplementedError()

class BasicStruct(BaseStruct):
    def __init__(self, fmt):
        # type: (str) -> None
        self.__struct = Struct(fmt)
    
    @property
    def size(self):
        # type: () -> int
        return self.__struct.size
    
    def unpack_from(self, buffer, offset=0):
        # type: (BufferType, int) -> Any
        value = self.__struct.unpack_from(buffer, offset)
        if len(value) > 0:
            return value[0]
        return None

class ArraySruct(BaseStruct):
    def __init__(self, struct, count) -> None:
        # type: (BaseStruct, int) -> None
        self.__struct = struct
        self.__count = count
    
    @property
    def size(self):
        # type: () -> int
        return self.__struct.size * self.__count
    
    def unpack_from(self, buffer, offset=0):
        # type: (BufferType, int) -> Any
        value = []
        for _ in range(self.__count):
            value.append(self.__struct.unpack_from(buffer, offset))
            offset += self.__struct.size
            # empty struct array, skip
            if value[0] == None:
                return None
        return value

class DictStruct(BaseStruct):
    def __init__(self, *fields) -> None:
        # type: (Tuple[str, BaseStruct] ) -> None
        self.__fields = fields
        self.__size = 0
        for field_name, field_type in fields:
            assert isinstance(field_type, BaseStruct)
            self.__size += field_type.size

    @property
    def size(self):
        # type: () -> int
        return self.__size

    def unpack_from(self, buffer, offset=0):
        # type: (BufferType, int) -> Any
        d = dict()
        for field_name, field_type in self.__fields:
            value = field_type.unpack_from(buffer, offset)
            if field_name != None and field_name != "":
                d[field_name] = value
            offset += field_type.size
        return d

class BytesStruct(BaseStruct):
    def __init__(self, size, adjust_string=False) -> None:
        # type: (int, bool) -> None
        self.__struct = Struct("{}s".format(size))
        self.__size = size
        self.__adjust = adjust_string
    
    @property
    def size(self):
        # type: () -> int
        return self.__size
    
    def unpack_from(self, buffer, offset=0):
        # type: (BufferType, int) -> Any
        value = self.__struct.unpack_from(buffer, offset)[0]
        if self.__adjust:
            return value[:value.index(b'\x00')].decode("utf-8")
        else:
            return value

class StringStruct(BytesStruct):
    def __init__(self, size) -> None:
        # type: (int, bool) -> None
        super().__init__(size, True)

struct_char = BasicStruct("c")
struct_unsigned_char = BasicStruct("B")
struct_short = BasicStruct("h")
struct_unsigned_short = BasicStruct("H")
struct_int = BasicStruct("i")
struct_unsigned_int = BasicStruct("I")
struct_long = BasicStruct("l")
struct_unsigned_long = BasicStruct("L")
struct_long_long = BasicStruct("q")
struct_unsigned_long_long = BasicStruct("Q")
struct_float = BasicStruct("f")
struct_double = BasicStruct("d")
struct_bool = BasicStruct("?")
struct_empty = BasicStruct("x")
