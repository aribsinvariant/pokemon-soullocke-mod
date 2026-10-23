-- Generated player script supplies SOUL_ADDRESS and SOUL_CONFIG before this file.
-- No internet connect call is made from mGBA's frame callback.
local base = assert(SOUL_ADDRESS, 'Missing build-specific mailbox address')
local config = assert(SOUL_CONFIG, 'Missing player configuration')
local peer, incoming, outgoing, sent, frames, lastState, lastPos = nil, '', '', 0, 0, 0, 0
local fatal, lastRomFrame = false, nil
local function read(offset) return emu:read32(base + offset) end
local function write(offset, value) emu:write32(base + offset, value) end
local function hex(offset, length)
    local parts = {}
    for i=0,length-1 do parts[#parts+1] = string.format('%02x', emu:read8(base+offset+i)) end
    return table.concat(parts)
end
local function unhex(value)
    assert(#value % 2 == 0 and not value:find('[^0-9a-f]'), 'Malformed relay data')
    return (value:gsub('..', function(byte) return string.char(tonumber(byte,16)) end))
end
local function bytes(offset, data)
    for i=1,#data do emu:write8(base + offset + i-1, data:byte(i)) end
end
local function send(line)
    if #outgoing > 65536 then fatal = true; error('Soul Link output queue overflow') end
    outgoing = outgoing .. line .. '\n'
end
local function disconnected()
    -- mGBA keeps a frame-poll callback for each accepted socket. Dropping the
    -- Lua reference alone leaves that callback and socket alive across retries.
    if peer then peer:close() end
    peer = nil
    incoming, outgoing = '', ''
    write(20, fatal and 3 or 0)
    write(104, 0)
end
local function receive(line)
    local words = {}
    for word in line:gmatch('%S+') do words[#words+1] = word end
    if words[1] == 'ERROR' then
        console:error('Soul Link: '..line:sub(7))
        fatal = true
        disconnected()
    elseif words[1] == 'STATE' then
        assert(#words == 12, 'Invalid snapshot length')
        local values = {}
        for i=2,10 do
            values[i] = assert(tonumber(words[i]), 'Invalid snapshot integer')
            assert(values[i] >= 0 and values[i] <= 4294967295 and values[i] % 1 == 0)
        end
        local trainer, records = unhex(words[11]), unhex(words[12])
        assert(#trainer == 8 and #records == 9216, 'Invalid snapshot payload')
        if read(24) ~= 0 and read(24) ~= values[2] then error('Save belongs to another run') end
        bytes(136, trainer)
        bytes(160, records)
        write(24, values[2]); write(124, values[4]); write(32, values[5]); write(36, values[6])
        write(40, values[7]); write(48, values[8]); write(44, values[10])
        write(28, config.player)
        write(116, values[3]+1) -- Zero is reserved for "no snapshot yet".
        write(20, values[9] == 1 and 2 or 1)
        write(16, read(16)+1)
        lastState = os.time()
    elseif words[1] == 'NOTICE' then
        assert(#words == 2 and (words[2] == '0' or words[2] == '1'))
        write(144, tonumber(words[2]))
    elseif words[1] == 'POS' then
        assert(#words == 8)
        for i=2,8 do assert(tonumber(words[i]) and tonumber(words[i]) >= 0 and tonumber(words[i]) <= 65535) end
        for i=2,7 do write(80+(i-2)*4, tonumber(words[i])) end
        write(104, tonumber(words[8]))
        lastPos = os.time()
    else
        error('Unknown relay message ('..#line..' bytes): '..string.format('%q', line:sub(1,80)))
    end
end
local function eventLine(index)
    local offset = 9376 + (index % 16)*48
    local seq, kind = read(offset), read(offset+4)
    local function arg(i) return read(offset+8+i*4) end
    local prefix = 'EVENT '..seq..' '
    if kind == 1 or kind == 9 then
        return prefix..(kind == 1 and 'catch ' or 'reserve ')..arg(0)..' '..arg(1)..' '..arg(2)..' '..arg(3)..' '..hex(offset+28,11)..' '..arg(4)
    elseif kind == 2 or kind == 3 then return prefix..(kind == 2 and 'death ' or 'fail ')..arg(0)
    elseif kind == 11 then return prefix..'finish '..arg(0)
    elseif kind == 10 then return prefix..'release '..arg(0)
    elseif kind == 4 then return prefix..'wipe'
    elseif kind == 5 or kind == 6 then return prefix..(kind == 5 and 'confirm ' or 'settings ')..arg(0)..' '..arg(1)
    elseif kind == 7 then
        local line = prefix..'party'
        assert(arg(0) <= 6)
        for i=1,arg(0) do line = line..' '..arg(i) end
        return line
    elseif kind == 8 then return prefix..'rename '..arg(0)..' '..hex(offset+28,11)..' '..arg(1)..' '..arg(2)
    end
    error('Unknown ROM event')
end
local listener = assert(socket.bind('127.0.0.1', config.local_port or 8766))
assert(listener:listen(1))
console:log('Soul Link bridge loaded. Start the Python connector, then press SELECT in the overworld.')
callbacks:add('frame', function()
    frames = frames + 1
    if read(0) ~= 0x534F554C then return end
    if read(4) ~= 1 or read(8) ~= 0x534C0001 then
        if not fatal then console:error('Soul Link ROM/build mismatch') end
        fatal = true; write(20,3); return
    end
    -- A bridge failure also sets connection=3. Preserve its original error instead
    -- of misreporting it as a fresh ROM failure on every subsequent frame.
    if fatal then write(20,3); return end
    if read(20) == 3 then
        console:error('ROM rejected synchronization (run='..read(24)..', queued='..(read(108)-read(112))..'). Reset the emulator and retry; keep this first error for diagnosis.')
        fatal = true
    end
    if lastRomFrame and read(12) < lastRomFrame then
        console:error('Save-state rollback is unsupported. Reset and load the in-game save to reconcile.')
        fatal = true
    end
    lastRomFrame = read(12)
    if fatal then write(20,3); return end
    local ok, err = pcall(function()
        if not peer then
            peer = listener:accept()
            if not peer then return end
            sent = read(112)
            incoming, outgoing = '', ''
            lastState = os.time()
            send('HELLO 1 '..read(8)..' '..config.room..' '..config.player..' '..config.token..' '..hex(128,8)..' '..read(24))
        end
        -- Bound work per emulator frame; handle partial TCP sends and receives.
        if peer:hasdata() then
            local data, problem = peer:receive(32768)
            if not data then
                if problem ~= socket.ERRORS.AGAIN then disconnected(); return end
            elseif #data == 0 then
                disconnected(); return
            else
                incoming = incoming .. data
                assert(#incoming <= 131072, 'Relay input queue overflow')
            end
        end
        -- Drain already-buffered lines even if no new bytes arrive this frame.
        for count=1,4 do
            local newline = incoming:find('\n',1,true)
            if not newline then break end
            local line = incoming:sub(1,newline-1)
            incoming = incoming:sub(newline+1)
            receive(line)
            if not peer then return end
        end
        if os.time() - lastState > 3 then disconnected(); return end
        if os.time() - lastPos > 2 then write(104,0) end
        write(16, read(16)+1)
        if frames % 6 == 0 then
            send('POS '..read(56)..' '..read(60)..' '..read(64)..' '..read(68)..' '..read(72)..' '..read(76)..' '..read(52))
        end
        if frames % 30 == 0 then send('POLL') end
        for i=1,4 do
            if sent >= read(108) then break end
            send(eventLine(sent)); sent = sent+1
        end
        if #outgoing > 0 then
            local written, problem = peer:send(outgoing)
            if written then outgoing = outgoing:sub(written+1)
            elseif problem ~= socket.ERRORS.AGAIN then disconnected(); return end
        end
    end)
    if not ok then
        console:error('Soul Link: '..tostring(err))
        fatal = true; disconnected()
    end
end)
callbacks:add('reset', function() fatal = false; lastRomFrame = nil; disconnected() end)
