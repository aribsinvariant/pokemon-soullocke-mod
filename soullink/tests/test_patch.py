import struct
import unittest
import zlib
from soullink.tools.package import bps


class PatchTests(unittest.TestCase):
    def test_roundtrip_grow_shrink_and_equal(self):
        for source,target in [(b'abcdef',b'aXYdefmore'),(b'abcdef',b'ab'),(b'abc',b'abc'),(b'',bytes(range(256))),(b'abc',b'')]:
            patch=bps(source,target)
            self.assertEqual(zlib.crc32(patch[:-4]),struct.unpack('<I',patch[-4:])[0])
            pos=4
            def readnum():
                nonlocal pos
                value,shift=0,1
                while True:
                    byte=patch[pos];pos+=1
                    value+=(byte&127)*shift
                    if byte&128:return value
                    shift<<=7;value+=shift
            self.assertEqual(readnum(),len(source))
            self.assertEqual(readnum(),len(target))
            metadata=readnum()
            pos+=metadata
            output=bytearray()
            while len(output)<len(target):
                command=readnum();size=(command>>2)+1
                if command&3==0:output+=source[len(output):len(output)+size]
                elif command&3==1:output+=patch[pos:pos+size];pos+=size
                else:self.fail('unexpected instruction')
            self.assertEqual(output,target)
            self.assertEqual(struct.unpack('<II',patch[-12:-4]),(zlib.crc32(source),zlib.crc32(target)))
