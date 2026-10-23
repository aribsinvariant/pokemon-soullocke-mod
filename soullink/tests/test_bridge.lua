-- Exercise the actual bridge with fragmented messages and partial socket writes.
SOUL_ADDRESS=0x02000000
SOUL_CONFIG={room='room',player=0,token='secret',local_port=8766}
local memory, frame, reset, accepted, packet, written = {}, nil, nil, false, nil, ''
local now, closed = 1000, 0
os.time = function() return now end
local function w(offset,value) memory[SOUL_ADDRESS+offset]=value end
emu={
 read32=function(_,a) return memory[a] or 0 end,
 write32=function(_,a,v) memory[a]=v end,
 read8=function(_,a) return memory[a] or 255 end,
 write8=function(_,a,v) memory[a]=v end,
}
console={log=function() end,error=function(_,s) error(s) end}
callbacks={add=function(_,kind,fn) if kind=='frame' then frame=fn elseif kind=='reset' then reset=fn end end}
local peer={
 hasdata=function() return packet~=nil end,
 receive=function()
   local p=packet;packet=nil
   if p==false then return nil,'again' end
   return p
 end,
 send=function(_,s) local n=math.min(19,#s);written=written..s:sub(1,n);return n end,
 close=function() closed=closed+1 end,
}
socket={ERRORS={AGAIN='again'},bind=function() return {
 listen=function() return 0 end,
 accept=function() if not accepted then accepted=true;return peer end end,
} end}
w(0,0x534F554C);w(4,1);w(8,0x534C0001)
dofile('soullink/bridge/bridge.lua')
for i=1,20 do frame() end
assert(written:find('HELLO 1 1397489665 room 0 secret ',1,true),written)
local state='STATE 123 7 0 97 42 1 0 1 1 '..string.rep('ff',8)..' '..string.rep('00',9216)..'\n'
packet=state:sub(1,100);frame();assert(memory[SOUL_ADDRESS+24]==nil)
packet=state:sub(101);frame()
assert(memory[SOUL_ADDRESS+24]==123)
assert(memory[SOUL_ADDRESS+116]==8)
assert(memory[SOUL_ADDRESS+20]==2)
packet='POS 257 8 9 2 1 4 1\n';frame()
assert(memory[SOUL_ADDRESS+80]==257 and memory[SOUL_ADDRESS+104]==1)
-- Pending event remains in the ROM ring until a durable relay acknowledgement.
w(108,1);w(112,0);w(9376,1);w(9380,2);w(9384,511)
for i=1,50 do frame() end
assert(written:find('EVENT 1 death 511\n',1,true),written)
assert(memory[SOUL_ADDRESS+112]==0)
print('bridge: fragmented snapshots, partial sends, position, and event encoding passed')

-- Finish buffered messages without needing another packet to wake the parser.
packet=string.rep('NOTICE 0\n',4)..'NOTICE 1\n'
frame();assert(memory[SOUL_ADDRESS+144]==0)
frame();assert(memory[SOUL_ADDRESS+144]==1)
-- A nonblocking read can race readiness; AGAIN must preserve the connection.
packet=false;frame();assert(closed==0)
-- Repeated focus pauses/reconnections must release the previous socket.
for i=1,8 do
    now=now+4;frame()
    assert(closed==i, 'Timed-out connection must close exactly once')
    accepted=false;frame()
end
reset();assert(closed==9, 'Reset must close the active connection')
reset();assert(closed==9, 'Reset without a peer must not close twice')
accepted=false;frame()
print('bridge: buffered input, nonblocking reads, timeout reconnections, and reset cleanup passed')

-- A relay error must remain the only diagnostic, not become a generic ROM error.
local errors = {}
console.error = function(_, message) errors[#errors+1] = message end
packet='UNEXPECTED test payload\n'
frame()
for i=1,5 do frame() end
assert(#errors == 1, 'Fatal errors must be reported once')
assert(errors[1]:find('UNEXPECTED test payload',1,true))
assert(errors[1]:find('23 bytes',1,true))
print('bridge: original fatal diagnostic preserved without repeated ROM errors')
