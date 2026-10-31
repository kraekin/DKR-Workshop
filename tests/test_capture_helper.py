"""Run the optional helper in standalone Lua with stubbed read-only APIs.

No emulator process is started and no game memory or save files are changed.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path

import pytest

LUA_DLL = Path(r'D:\RomHacking\Emulators\BizHawk-2.10-win-x64\dll\lua54.dll')
SCRIPT = Path(__file__).resolve().parents[1]/'src/core/bizhawk_capture.lua'


@pytest.mark.parametrize('reader', ('binary', 'array', 'legacy'))
@pytest.mark.parametrize('chunk_name', ('file', 'main', '=main'))
def test_lua_capture_reads_only_and_publishes_complete_dump(reader: str, chunk_name: str) -> None:
    if not LUA_DLL.exists():
        pytest.skip('Local standalone Lua runtime absent')
    lua = ctypes.CDLL(str(LUA_DLL))
    pointer = ctypes.c_void_p
    lua.luaL_newstate.restype = pointer
    lua.luaL_openlibs.argtypes = [pointer]
    lua.luaL_loadbufferx.argtypes = [pointer, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_char_p]
    lua.lua_pcallk.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ssize_t, pointer]
    lua.lua_tolstring.argtypes = [pointer, ctypes.c_int, pointer]
    lua.lua_tolstring.restype = ctypes.c_char_p
    lua.lua_close.argtypes = [pointer]
    state = lua.luaL_newstate()
    assert state
    def execute(code: bytes, name: bytes) -> None:
        result = lua.luaL_loadbufferx(state, code, len(code), name, None)
        if result == 0: result = lua.lua_pcallk(state, 0, 0, 0, 0, None)
        assert result == 0, lua.lua_tolstring(state, -1, None)
    try:
        lua.luaL_openlibs(state)
        expected_directory = (SCRIPT.parents[2]/'artifacts').as_posix()+'/'
        execute(('expected_directory='+json.dumps(expected_directory)).encode(), b'@capture-destination')
        execute(b'''
            written, reads, closed, renamed, messages = 0, 0, 0, 0, 0
            emu = { getsystemid = function() return "N64" end }
            memory = {
                getmemorydomainlist = function() return {"RDRAM"} end,
                getmemorydomainsize = function(domain) assert(domain=="RDRAM"); return 0x400000 end
            }
            io.open = function(path, mode)
                assert(path:sub(1,#expected_directory)==expected_directory)
                if mode=="rb" then return nil end
                assert(mode=="wb" and path:sub(-5)==".part")
                return {
                    write = function(self, data) written=written+#data; assert(data==string.rep("Z",#data)); return self end,
                    close = function() closed=closed+1; return true end
                }
            end
            os.rename = function(a,b) assert(a==b..".part"); renamed=renamed+1; return true end
            console = { log = function(message) assert(type(message)=="string"); messages=messages+1 end }
        ''', b'@capture-stubs')
        if reader == 'binary':
            setup = 'memory.read_bytes_as_binary_string = function(a,n,d) assert(d=="RDRAM"); reads=reads+1; return string.rep("Z",n) end'
        else:
            name = 'read_bytes_as_array' if reader == 'array' else 'readbyterange'
            first = 1 if reader == 'array' else 0
            setup = f'memory.{name}=function(a,n,d) assert(d=="RDRAM"); reads=reads+1; local t={{}}; for i=0,n-1 do t[i+{first}]=90 end; return t end'
        execute(setup.encode(), b'@capture-reader')
        chunk = ('@'+str(SCRIPT)) if chunk_name == 'file' else chunk_name
        execute(SCRIPT.read_bytes(), chunk.encode())
        execute(b'assert(written==0x400000 and reads==1024 and closed==1 and renamed==1 and messages==3)', b'@capture-assertions')
    finally:
        lua.lua_close(state)
