-- Optional one-shot RDRAM capture for BizHawk 2.10. Run from its Lua Console.
-- Reads memory only; does not advance frames, change input, write game memory,
-- load/save states or alter ROM/save RAM. Reload the script for another sample.
-- API: https://tasvideos.org/Bizhawk/LuaFunctions (memory read APIs).

-- BizHawk loads files as [string "main"], so Lua debug metadata does not
-- contain the file path. Keep the destination explicit; change it if moving
-- this project. The existing artifacts directory is ignored by the project.
local OUTPUT_DIRECTORY = [[D:/RomHacking/n64/dkr/artifacts]]

assert(emu.getsystemid() == "N64", "Load your DKR ROM in BizHawk first")
local domain = nil
for _, name in pairs(memory.getmemorydomainlist()) do
    if name == "RDRAM" then domain = name end
end
assert(domain, "This core has no RDRAM domain; use a BizHawk Mupen64Plus savestate instead")
local size = memory.getmemorydomainsize(domain)
assert(size == 0x400000 or size == 0x800000, "Expected 4 MiB or 8 MiB RDRAM")

local prefix = OUTPUT_DIRECTORY .. "/dkr-rdram-" .. os.date("%Y%m%d-%H%M%S")
local output, temporary = nil, nil
for serial = 1, 999 do
    local candidate = prefix .. "-" .. serial .. ".bin"
    local existing = io.open(candidate, "rb")
    local partial = io.open(candidate .. ".part", "rb")
    if existing then existing:close() end
    if partial then partial:close() end
    if not existing and not partial then
        output, temporary = candidate, candidate .. ".part"
        break
    end
end
assert(output, "No unused capture filename available")
local handle, reason = io.open(temporary, "wb")
assert(handle, "Cannot create capture in project artifacts: " .. tostring(reason))

local ok, failure = pcall(function()
    for address = 0, size - 1, 4096 do
        local count = math.min(4096, size - address)
        local bytes
        if memory.read_bytes_as_binary_string then
            bytes = memory.read_bytes_as_binary_string(address, count, domain)
        else
            local array, first
            if memory.read_bytes_as_array then
                array, first = memory.read_bytes_as_array(address, count, domain), 1
            else
                assert(memory.readbyterange, "This BizHawk has no supported bulk memory reader")
                array, first = memory.readbyterange(address, count, domain), 0
            end
            local characters = {}
            for i = 0, count - 1 do characters[i + 1] = string.char(array[first + i]) end
            bytes = table.concat(characters)
        end
        assert(#bytes == count, "Incomplete RDRAM read")
        assert(handle:write(bytes))
    end
end)
local closed, close_error = handle:close()
if not ok or not closed then
    os.remove(temporary)
    error("Capture failed: " .. tostring(failure or close_error))
end
local renamed, rename_error = os.rename(temporary, output)
assert(renamed, "Capture remains at " .. temporary .. ": " .. tostring(rename_error))
console.log("DKR RDRAM snapshot saved: " .. output)
console.log("Editor: File > ROM Budget and Project Changes > Load runtime snapshot")
console.log("Observed state only. This sample does not establish a safe extra-object count.")
