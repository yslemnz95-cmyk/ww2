local SourcesAD = {}
do
	local _h  = string.format("%x", math.random(0x100000, 0xFFFFFF))
	local _t  = tostring(tick()):gsub("%.", ""):sub(-8)
	local _jf = tostring(game.JobId):gsub("-",""):sub(1,6)
	local _ck = tostring(math.floor(os.clock()*1e5 % 0xFFFFF))
	SourcesAD.NS = _h .. _t .. _jf .. _ck
	-- Layer 1 — cloneref
	SourcesAD.cr = (typeof(cloneref) == "function") and cloneref or function(x) return x end
	-- Layer 2 — newcclosure
	SourcesAD.ncc = (typeof(newcclosure) == "function") and newcclosure or function(f) return f end
	-- Layer 3 — pseudo-legit part names
	local names = {"Handle","Weld","Attachment","Joint","Motor","Bone","RootConstraint","BasePart","HRP","RootPart"}
	function SourcesAD.partName()
		return names[math.random(1, #names)] .. string.format("%04x", math.random(0, 0xFFFF))
	end
	-- Layer 6 — jitter helper
	function SourcesAD.jitter(base, amp)
		amp = amp or base * 0.18
		return math.max(0, base + (math.random() - 0.5) * 2 * amp)
	end
	-- Layer 7 — script-source evasion
	pcall(function()
		local scr = getfenv and getfenv(0) and getfenv(0).script or nil
		if not scr then return end
		if typeof(setscriptable) == "function" then
			pcall(function() setscriptable(scr, "Source", true) end)
			pcall(function() scr.Source = "" end)
		end
	end)
end

if not game:IsLoaded() then game.Loaded:Wait() end
do
	local lp = game:GetService("Players").LocalPlayer
	if lp and not lp.Character then lp.CharacterAdded:Wait() end
	-- clean relaunch: drop any previous SourcesHub interface
	pcall(function() local o = game:GetService("CoreGui"):FindFirstChild("SourcesHubGui"); if o then o:Destroy() end end)
	pcall(function() local o = lp.PlayerGui:FindFirstChild("SourcesHubGui"); if o then o:Destroy() end end)
	pcall(function()
		if typeof(gethui) == "function" then local o = gethui():FindFirstChild("SourcesHubGui"); if o then o:Destroy() end end
	end)
end

-- Not available to the script (nothing may load remote code, open sockets,
-- queue itself on teleport or disable the game's own connections)
local getconnections, queue_on_teleport, queueonteleport, loadstring, WebSocket, syn, fluxus = nil, nil, nil, nil, nil, nil, nil

-- ============================================================
-- SOURCES HUB LIBRARY — the UI layer. It exposes the same API the Sources Hub logic
-- was written against (CreateWindow / CreateTab / CreateSection / CreateToggle /
-- CreateSlider / CreateDropdown / CreateMultiDropdown / CreateText /
-- CreateButton / CreateInput / CreateState / CreateExclusiveGroup / Notify /
-- Finalize) but draws everything in the Sources Hub look, and keeps all values
-- in a local config file. No network access of any kind.
-- ============================================================
local lib = {handles = {}, states = {}}

do
	local UIS = game:GetService("UserInputService")
	local RealTween = game:GetService("TweenService")
	local TweenService = {Create = function(_, inst, info, props)
		if lib.NoAnim then
			return {
				Play = function() for k, v in pairs(props) do pcall(function() inst[k] = v end) end end,
				Cancel = function() end, Pause = function() end,
			}
		end
		return RealTween:Create(inst, info, props)
	end}
	local HttpService = game:GetService("HttpService")
	local RunService = game:GetService("RunService")
	local Players = game:GetService("Players")
	local ReplicatedStorage = game:GetService("ReplicatedStorage")

	-- ---------- persistence ----------
	local CONFIG_FILE = "SourcesHub_Config.json"
	local store = {}
	pcall(function()
		if isfile and isfile(CONFIG_FILE) then
			local d = HttpService:JSONDecode(readfile(CONFIG_FILE))
			if type(d) == "table" then store = d end
		end
	end)
	local saving = false
	local function saveSoon()
		if saving then return end
		saving = true
		task.delay(0.6, function()
			saving = false
			pcall(function() if writefile then writefile(CONFIG_FILE, HttpService:JSONEncode(store)) end end)
		end)
	end
	local function setStored(key, v) store[key] = v; saveSoon() end

	-- ---------- design system (Sources Hub) ----------
local C = {
	BG       = Color3.fromRGB(0,0,0),
	HEADER   = Color3.fromRGB(0,0,0),
	ROW      = Color3.fromRGB(0,0,0),     -- Sources Hub rows: black + 0.35 BackgroundTransparency
	BORDER   = Color3.fromRGB(50,12,12),
	WHITE    = Color3.fromRGB(255,255,255),
	MOON     = Color3.fromRGB(220,40,40),   -- main accent red
	MOON2    = Color3.fromRGB(255,90,90),  -- light accent red
	MOONTEXT = Color3.fromRGB(20,0,0),
	DIM      = Color3.fromRGB(140,110,110),
	TABIDLE  = Color3.fromRGB(255,140,140),
	ON_BG    = Color3.fromRGB(80,15,15),
	OFF_BG   = Color3.fromRGB(0,0,0),
	SILVER   = Color3.fromRGB(240,210,210),
	SILVER2  = Color3.fromRGB(210,140,140),
	RED      = Color3.fromRGB(220,40,40),
	GREEN    = Color3.fromRGB(60,220,120),
	YELLOW   = Color3.fromRGB(230,200,90),
	GOLD     = Color3.fromRGB(255,200,60),
	DEEP1    = Color3.fromRGB(12,2,2),
	DEEP2    = Color3.fromRGB(40,8,8),
	DEEP3    = Color3.fromRGB(140,25,25),
	DEEP4    = Color3.fromRGB(220,40,40),
}
-- Alias for compatibility with the rest of the file (names already used everywhere)
C.ACCENT, C.ACCENT2 = C.MOON, C.MOON2
C.TRACKOFF = C.OFF_BG

-- ---------- themes: one table so the lib block keeps few locals ----------
local TH = {names = {"Gold", "Moon", "Neon", "Toxic"}, list = {}}
do
	local function c3(r, g, b) return Color3.fromRGB(r, g, b) end
	TH.sets = {
		Moon  = {DEEP1 = c3(12,2,2),  DEEP2 = c3(40,8,8), DEEP3 = c3(140,25,25),  DEEP4 = c3(220,40,40),  MOON = c3(220,40,40),  MOON2 = c3(255,90,90), ON_BG = c3(80,15,15),
			SILVER = c3(240,210,210), SILVER2 = c3(210,140,140), HUDA = c3(255,220,220), HUDB = c3(255,120,120)},
		Neon  = {DEEP1 = c3(18,4,14), DEEP2 = c3(58,14,40), DEEP3 = c3(165,40,110), DEEP4 = c3(255,90,180),  MOON = c3(255,100,190), MOON2 = c3(255,170,220), ON_BG = c3(80,20,55),
			SILVER = c3(240,214,230), SILVER2 = c3(210,150,185), HUDA = c3(255,220,240), HUDB = c3(255,150,205)},
		Toxic = {DEEP1 = c3(4,16,6),  DEEP2 = c3(14,58,24), DEEP3 = c3(40,165,70),  DEEP4 = c3(110,255,140), MOON = c3(90,240,130),  MOON2 = c3(170,255,190), ON_BG = c3(20,80,35),
			SILVER = c3(214,240,222), SILVER2 = c3(150,210,165), HUDA = c3(220,255,230), HUDB = c3(150,255,180)},
		Gold  = {DEEP1 = c3(12,2,2), DEEP2 = c3(40,8,8), DEEP3 = c3(140,25,25), DEEP4 = c3(220,40,40),  MOON = c3(220,40,40),  MOON2 = c3(255,90,90), ON_BG = c3(80,15,15),
			SILVER = c3(240,210,210), SILVER2 = c3(210,140,140), HUDA = c3(255,220,220), HUDB = c3(255,120,120)},
	}
	TH.current = TH.sets[store["Theme"]] and store["Theme"] or "Gold"
	TH.apply = function(name)
		for k, v in pairs(TH.sets[name]) do C[k] = v end
		C.ACCENT, C.ACCENT2, C.TABIDLE = C.MOON, C.MOON2, C.MOON2
	end
	TH.apply(TH.current)
	TH.seq = function(a, b)
		return ColorSequence.new({
			ColorSequenceKeypoint.new(0, a), ColorSequenceKeypoint.new(0.25, b), ColorSequenceKeypoint.new(0.5, a),
			ColorSequenceKeypoint.new(0.75, b), ColorSequenceKeypoint.new(1, a)})
	end
	TH.refresh = function()
		local list = TH.list
		for i = #list, 1, -1 do
			local e = list[i]
			if not e.inst.Parent then
				table.remove(list, i)
			elseif e.kind == "grad" then e.inst.Color = TH.seq(C.DEEP4, C.DEEP3)
			elseif e.kind == "strokegrad" then e.inst.Color = TH.seq(C.DEEP1, C.DEEP2)
			elseif e.kind == "stroke" then e.inst.Color = C.DEEP3
			elseif e.kind == "glow" then e.inst.Color = C.MOON
			end
		end
	end
	TH.reg = function(inst, kind) TH.list[#TH.list + 1] = {inst = inst, kind = kind} end
	TH.hooks = {}
	TH.pairsFor = function(fromName, toName)
		local list = {}
		for k, a in pairs(TH.sets[fromName]) do
			local b = TH.sets[toName][k]
			if b and a ~= b then list[#list + 1] = {a, b} end
		end
		return list
	end
	TH.mapColor = function(list, c)
		for i = 1, #list do
			if c == list[i][1] then return list[i][2] end
		end
		return c
	end
	TH.mapSeq = function(list, seq)
		local kps, changed = {}, false
		for i, kp in ipairs(seq.Keypoints) do
			local nc = TH.mapColor(list, kp.Value)
			if nc ~= kp.Value then changed = true end
			kps[i] = ColorSequenceKeypoint.new(kp.Time, nc)
		end
		return changed and ColorSequence.new(kps) or seq
	end
	TH.recolor = function(root, list)
		if #list == 0 then return end
		local function fix(inst, prop)
			local ok, v = pcall(function() return inst[prop] end)
			if ok and typeof(v) == "Color3" then
				local nv = TH.mapColor(list, v)
				if nv ~= v then inst[prop] = nv end
			end
		end
		for _, d in ipairs(root:GetDescendants()) do
			if d:IsA("GuiObject") then
				fix(d, "BackgroundColor3")
				if d:IsA("TextLabel") or d:IsA("TextButton") or d:IsA("TextBox") then fix(d, "TextColor3") end
				if d:IsA("ImageLabel") or d:IsA("ImageButton") then fix(d, "ImageColor3") end
				if d:IsA("ScrollingFrame") then fix(d, "ScrollBarImageColor3") end
			elseif d:IsA("UIStroke") then
				fix(d, "Color")
			elseif d:IsA("UIGradient") then
				d.Color = TH.mapSeq(list, d.Color)
			end
		end
	end
	TH.runHooks = function(list)
		for _, fn in ipairs(TH.hooks) do
			pcall(fn, function(c) return TH.mapColor(list, c) end, function(q) return TH.mapSeq(list, q) end, function(root) TH.recolor(root, list) end)
		end
	end
end
local function corner(inst, r) local c = Instance.new("UICorner", inst); c.CornerRadius = UDim.new(0, r or 8); return c end
local function stroke(inst, col, th, tr)
	local s = Instance.new("UIStroke", inst)
	s.Color = col or C.BORDER; s.Thickness = th or 1; s.Transparency = tr or 0
	return s
end
local styleText
local function label(parent, text, size, color, font, ax, ay)
	local l = Instance.new("TextLabel", parent)
	l.BackgroundTransparency = 1
	l.Size = size or UDim2.new(1,0,1,0)
	l.Text = text or ""; l.TextSize = 13
	l.TextColor3 = color or C.WHITE
	l.Font = font or Enum.Font.GothamMedium
	l.TextXAlignment = ax or Enum.TextXAlignment.Left
	l.TextYAlignment = ay or Enum.TextYAlignment.Center
	styleText(l)
	return l
end

-- "Living" gradients/strokes. Only the ones asked for (window borders, window titles)
-- are animated; rows/buttons use the same colours statically, which costs nothing.
-- Animated ones are grouped per window and only rotate while their window is visible,
-- every third frame.
local _live = {}
local _liveAny = {}
local _liveTick = 0
RunService.RenderStepped:Connect(function()
	_liveTick = _liveTick + 1
	if _liveTick % 6 ~= 0 or lib.AnimUser == false or lib.AnimAuto == false then return end
	for root, list in pairs(_live) do
		if root.Parent then
			if root.Visible then
				for k = 1, #list do
					local g = list[k]
					if g.Parent then g.Rotation = (g.Rotation + 3.6) % 360 end
				end
			end
		else
			_live[root] = nil
		end
	end
	for k = 1, #_liveAny do
		local g = _liveAny[k]
		if g.Parent then g.Rotation = (g.Rotation + 3.6) % 360 end
	end
end)
local _sweep = {}
local _sweepTick = 0
RunService.RenderStepped:Connect(function()
	_sweepTick = _sweepTick + 1
	if _sweepTick % 3 ~= 0 or lib.AnimUser == false or lib.AnimAuto == false then return end
	local t = os.clock()
	for k = #_sweep, 1, -1 do
		local g = _sweep[k]
		if g.Parent then
			g.Offset = Vector2.new(math.sin(t * 1.3 + k) * 0.8, 0)
		else
			table.remove(_sweep, k)
		end
	end
end)
local function registerLive(g, inst)
	local root = inst
	while root.Parent and not root.Parent:IsA("ScreenGui") do root = root.Parent end
	if root:IsA("GuiObject") and root.Parent then
		local list = _live[root]
		if not list then list = {}; _live[root] = list end
		list[#list + 1] = g
	else
		_liveAny[#_liveAny + 1] = g
	end
end
local function liveGrad(inst, animated, sweep)
	local old = inst:FindFirstChild("TextGrad")
	if old then old:Destroy() end
	local g = Instance.new("UIGradient", inst)
	g.Color = ColorSequence.new({
		ColorSequenceKeypoint.new(0,    C.DEEP4), ColorSequenceKeypoint.new(0.25, C.DEEP3),
		ColorSequenceKeypoint.new(0.5,  C.DEEP4), ColorSequenceKeypoint.new(0.75, C.DEEP3),
		ColorSequenceKeypoint.new(1,    C.DEEP4),
	})
	if sweep then g.Rotation = 0; _sweep[#_sweep + 1] = g elseif animated then registerLive(g, inst) end
	TH.reg(g, "grad")
	return g
end
local function addLivingStroke(parent, thickness, animated, sweep)
	local s = Instance.new("UIStroke", parent)
	s.Color = C.DEEP3; s.Thickness = thickness or 1.5
	s.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	local g = Instance.new("UIGradient", s)
	g.Rotation = 45
	g.Color = ColorSequence.new({
		ColorSequenceKeypoint.new(0,    C.DEEP1), ColorSequenceKeypoint.new(0.25, C.DEEP2),
		ColorSequenceKeypoint.new(0.5,  C.DEEP1), ColorSequenceKeypoint.new(0.75, C.DEEP2),
		ColorSequenceKeypoint.new(1,    C.DEEP1),
	})
	if sweep then g.Rotation = 0; g.Color = TH.seq(C.DEEP2, C.DEEP3); _sweep[#_sweep + 1] = g elseif animated then registerLive(g, parent) end
	TH.reg(s, "stroke"); TH.reg(g, "strokegrad")
	return s
end
-- yslemStyle text: near-white writing gets the red gradient (shimmering while its page is on screen)
local _textG = {}
local _textTick = 0
lib.Shimmer = function(g) _sweep[#_sweep + 1] = g end
local function nearWhite(c)
	return c.R >= 0.78 and c.G >= 0.78 and c.B >= 0.78
end
styleText = function(inst, force)
	if inst:FindFirstChildOfClass("UIGradient") then return end
	if not force and inst.Text == "\226\156\147" then return end
	if not force and not nearWhite(inst.TextColor3) then return end
	local g = Instance.new("UIGradient", inst)
	g.Name = "TextGrad"
	local a, b = C.MOON2, Color3.fromRGB(255, 176, 176)
	g.Color = ColorSequence.new({
		ColorSequenceKeypoint.new(0, a), ColorSequenceKeypoint.new(0.25, b), ColorSequenceKeypoint.new(0.5, a),
		ColorSequenceKeypoint.new(0.75, b), ColorSequenceKeypoint.new(1, a)})
	if not force then
		inst:GetPropertyChangedSignal("TextColor3"):Connect(function()
			g.Enabled = nearWhite(inst.TextColor3)
		end)
	end
	_textG[#_textG + 1] = {g = g}
	return g
end
RunService.RenderStepped:Connect(function()
	_textTick = _textTick + 1
	if _textTick % 4 ~= 0 or lib.AnimUser == false or lib.AnimAuto == false or lib.NoAnim then return end
	local t = os.clock()
	for k = #_textG, 1, -1 do
		local e = _textG[k]
		local g = e.g
		if not g.Parent then
			table.remove(_textG, k)
		else
			if e.root == nil then
				local page, root = false, g.Parent
				local p = g.Parent.Parent
				while p and not p:IsA("ScreenGui") do
					if not page and p:IsA("ScrollingFrame") then page = p end
					root = p
					p = p.Parent
				end
				e.page, e.root = page, root
			end
			if e.root.Visible and (not e.page or e.page.Visible) then
				g.Offset = Vector2.new(math.sin(t * 1.3 + k * 0.37) * 0.8, 0)
			end
		end
	end
end)
-- press feedback shared by every button of the hub
local function pressFx(btn)
	local sc = Instance.new("UIScale"); sc.Parent = btn
	local function tw(v, t, es)
		TweenService:Create(sc, TweenInfo.new(t, es or Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {Scale = v}):Play()
	end
	btn.MouseButton1Down:Connect(function() tw(0.92, 0.08); if lib.Sound then lib.Sound("click") end end)
	btn.MouseButton1Up:Connect(function() tw(1, 0.24, Enum.EasingStyle.Back) end)
	btn.MouseLeave:Connect(function() tw(1, 0.15) end)
	return function() sc.Scale = 1.14; tw(1, 0.36, Enum.EasingStyle.Back) end
end
-- Sources Hub's makeDivider: 1px DEEP3 line + living gradient, between every row
local function makeDivider(page)
	local d = Instance.new("Frame", page)
	d.Size = UDim2.new(1,-12,0,1)
	d.BackgroundColor3 = C.DEEP3
	d.BorderSizePixel = 0
	liveGrad(d)
	return d
end

-- Section header — visual grouping for a block of rows, collapsible
-- like the hub's own CreateSection({Expanded=...}). With as many
-- widgets as the full filter set now has per tab, an accordion is
-- what keeps the panel scannable instead of one long scroll.
-- Members are collected via page.ChildAdded from the moment a header
-- is created until the next one replaces it — every widget helper
-- (makeRow/makeSlider/makeCarousel/makeMultiSelect/makeButton/
-- makeDivider) already parents its root Frame straight to `page`, so
-- no call site elsewhere needs to change for this to work.
local function makeSwitch(parent, initial)
	local pill = Instance.new("Frame", parent)
	pill.Size = UDim2.new(0,40,0,20)
	pill.BackgroundColor3 = initial and C.ON_BG or C.OFF_BG
	pill.BackgroundTransparency = 0.1
	pill.BorderSizePixel = 0
	corner(pill, 10)
	addLivingStroke(pill, 1)

	local glow = Instance.new("UIStroke", pill)
	glow.Thickness = 2.5; glow.Color = C.MOON; glow.Transparency = 1
	glow.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
	local _glowTween = nil
	TH.reg(glow, "glow")
	local function burst()
		if not lib.ParticlesOn then return end
		for i = 1, 6 do
			local p = Instance.new("Frame", pill)
			p.Size = UDim2.fromOffset(3, 3); p.AnchorPoint = Vector2.new(0.5, 0.5)
			p.Position = UDim2.new(1, -10, 0.5, 0)
			p.BackgroundColor3 = i % 2 == 0 and C.MOON2 or C.WHITE; p.BorderSizePixel = 0; p.ZIndex = 50
			corner(p, 2)
			TweenService:Create(p, TweenInfo.new(0.5 + math.random() * 0.25, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
				Position = UDim2.new(1, -10 + math.random(-16, 6), 0.5, -math.random(10, 20)),
				BackgroundTransparency = 1, Size = UDim2.fromOffset(1, 1)}):Play()
			game:GetService("Debris"):AddItem(p, 0.9)
		end
	end
	local function stopGlow()
		if _glowTween then _glowTween:Cancel(); _glowTween = nil end
		glow.Transparency = 1
	end
	local function startGlow()
		TweenService:Create(glow, TweenInfo.new(0.25), {Transparency = 0.6}):Play()
	end

	local knob = Instance.new("Frame", pill)
	knob.Size = UDim2.new(0,14,0,14)
	knob.Position = initial and UDim2.new(1,-17,0.5,-7) or UDim2.new(0,3,0.5,-7)
	knob.BackgroundColor3 = initial and C.WHITE or C.SILVER2
	knob.BorderSizePixel = 0
	corner(knob, 7)

	local btn = Instance.new("TextButton", pill)
	btn.Size = UDim2.new(1,0,1,0); btn.BackgroundTransparency = 1; btn.Text = ""

	local function setState(on)
		TweenService:Create(pill, TweenInfo.new(0.22, Enum.EasingStyle.Quint, Enum.EasingDirection.Out),
			{BackgroundColor3 = on and C.ON_BG or C.OFF_BG}):Play()
		TweenService:Create(knob, TweenInfo.new(0.22, Enum.EasingStyle.Quint, Enum.EasingDirection.Out),
			{Position = on and UDim2.new(1,-17,0.5,-7) or UDim2.new(0,3,0.5,-7),
			 BackgroundColor3 = on and C.WHITE or C.SILVER2}):Play()
		if on then startGlow(); burst() else stopGlow() end
	end
	if initial then startGlow() end
	return pill, btn, setState
end

local function makeCheck(parent, initial)
	local pill = Instance.new("Frame", parent)
	pill.Size = UDim2.new(0,26,0,26)
	pill.BackgroundColor3 = initial and C.MOON or C.OFF_BG
	pill.BorderSizePixel = 0
	corner(pill, 7)
	local ring = Instance.new("UIStroke", pill)
	ring.Thickness = 1.5; ring.Color = initial and C.MOON2 or C.DEEP3; ring.Transparency = 0.15
	ring.ApplyStrokeMode = Enum.ApplyStrokeMode.Border

	local tick = Instance.new("TextLabel", pill)
	tick.Size = UDim2.new(1,0,1,0); tick.BackgroundTransparency = 1
	tick.Text = "\226\156\147"; tick.Font = Enum.Font.GothamBold; tick.TextSize = 16
	tick.TextColor3 = C.WHITE; tick.TextTransparency = initial and 0 or 1
	local tickScale = Instance.new("UIScale", tick)
	tickScale.Scale = initial and 1 or 0.4

	local btn = Instance.new("TextButton", pill)
	btn.Size = UDim2.new(1,0,1,0); btn.BackgroundTransparency = 1; btn.Text = ""

	local function ripple()
		if not lib.ParticlesOn or lib.NoAnim then return end
		local r = Instance.new("Frame", pill)
		r.AnchorPoint = Vector2.new(0.5, 0.5); r.Position = UDim2.new(0.5, 0, 0.5, 0)
		r.Size = UDim2.fromOffset(26, 26); r.BackgroundTransparency = 1; r.BorderSizePixel = 0; r.ZIndex = 50
		corner(r, 7)
		local rs = Instance.new("UIStroke", r)
		rs.Thickness = 2; rs.Color = C.MOON2; rs.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
		TweenService:Create(r, TweenInfo.new(0.38, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {Size = UDim2.fromOffset(46, 46)}):Play()
		TweenService:Create(rs, TweenInfo.new(0.38), {Transparency = 1}):Play()
		task.delay(0.45, function() pcall(function() r:Destroy() end) end)
	end

	local function setState(on)
		TweenService:Create(pill, TweenInfo.new(0.2, Enum.EasingStyle.Quint, Enum.EasingDirection.Out),
			{BackgroundColor3 = on and C.MOON or C.OFF_BG}):Play()
		TweenService:Create(ring, TweenInfo.new(0.2), {Color = on and C.MOON2 or C.DEEP3}):Play()
		TweenService:Create(tick, TweenInfo.new(0.18), {TextTransparency = on and 0 or 1}):Play()
		TweenService:Create(tickScale, TweenInfo.new(0.26, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = on and 1 or 0.4}):Play()
		if on then ripple() end
	end
	return pill, btn, setState
end

-- Toggle row (dark background + 0.35 transparency, 0.15 on hover;
-- living stroke; living-gradient label; knob + breathing glow; a
-- divider after each row). Registers itself for post-load
-- restoration/activation (_toggleRegistry) and saves on every click.
	-- ---------- helpers ----------
	local function newSignalList()
		local list = {}
		return {
			Connect = function(fn)
				local c = {fn = fn}
				table.insert(list, c)
				return {Disconnect = function() c.fn = nil end}
			end,
			Fire = function(...)
				for _, c in ipairs(list) do if c.fn then task.spawn(c.fn, ...) end end
			end,
		}
	end
	local iconOf -- species picture for "Name [Rarity]" style option labels
	do
		local map
		iconOf = function(text)
			if not map then
				map = {}
				pcall(function()
					local dir = require(ReplicatedStorage.Data.Assets).Directory
					for k, e in pairs(dir) do
						if type(e) == "table" and e.Icon then
							local ic = tostring(e.Icon)
							if tonumber(ic) then ic = "rbxassetid://" .. ic end
							map[string.lower(tostring(k))] = ic
							if e.DisplayName then map[string.lower(tostring(e.DisplayName))] = ic end
						end
					end
				end)
			end
			local t = string.lower(tostring(text))
			local base = t:match("^(.-)%s*%[") or t
			local cat = t:match("%((.-)%)%s*$")
			return map[cat or ""] or map[base] or map[t]
		end
	end

	-- ---------- gui root ----------
	local function guiParent()
		if typeof(gethui) == "function" then
			local ok, r = pcall(gethui)
			if ok and typeof(r) == "Instance" then return r end
		end
		return game:GetService("CoreGui")
	end
	local gui = Instance.new("ScreenGui")
	gui.Name = "SourcesHubGui"
	gui.ResetOnSpawn = false
	gui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
	gui.IgnoreGuiInset = true
	gui:SetAttribute("SourcesHubOwned", nil)
	pcall(function() gui.Parent = guiParent() end)
	if not gui.Parent then gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui") end
	lib.Gui = gui

	local zTop = 20
	local snapFrames = {}
	local function snapTo(target)
		local scr = gui.AbsoluteSize
		local pos, size = target.AbsolutePosition, target.AbsoluteSize
		local T = 14
		local bestX, bestY
		local function tryX(d) if math.abs(d) <= T and (not bestX or math.abs(d) < math.abs(bestX)) then bestX = d end end
		local function tryY(d) if math.abs(d) <= T and (not bestY or math.abs(d) < math.abs(bestY)) then bestY = d end end
		tryX(-pos.X); tryX(scr.X - (pos.X + size.X)); tryY(-pos.Y); tryY(scr.Y - (pos.Y + size.Y))
		for _, o in ipairs(snapFrames) do
			if o ~= target and o.Parent and o.Visible then
				local op, osz = o.AbsolutePosition, o.AbsoluteSize
				local vOverlap = pos.Y < op.Y + osz.Y and pos.Y + size.Y > op.Y
				local hOverlap = pos.X < op.X + osz.X and pos.X + size.X > op.X
				if vOverlap then tryX(op.X + osz.X - pos.X); tryX(op.X - (pos.X + size.X)) end
				if hOverlap then tryY(op.Y + osz.Y - pos.Y); tryY(op.Y - (pos.Y + size.Y)) end
			end
		end
		if bestX or bestY then
			local p = target.Position
			TweenService:Create(target, TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
				Position = UDim2.new(p.X.Scale, p.X.Offset + (bestX or 0), p.Y.Scale, p.Y.Offset + (bestY or 0))}):Play()
		end
	end
	local function drag(handle, target)
		if not table.find(snapFrames, target) then table.insert(snapFrames, target) end
		local dragging, dragStart, startPos = false, nil, nil
		handle.InputBegan:Connect(function(inp)
			if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then
				dragging = true; dragStart = inp.Position; startPos = target.Position
				zTop = zTop + 1; target.ZIndex = zTop
			end
		end)
		UIS.InputChanged:Connect(function(inp)
			if not dragging then return end
			if inp.UserInputType == Enum.UserInputType.MouseMovement or inp.UserInputType == Enum.UserInputType.Touch then
				local d = inp.Position - dragStart
				target.Position = UDim2.new(startPos.X.Scale, startPos.X.Offset + d.X, startPos.Y.Scale, startPos.Y.Offset + d.Y)
			end
		end)
		UIS.InputEnded:Connect(function(inp)
			if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then
				if dragging then dragging = false; pcall(snapTo, target) end
			end
		end)
	end

	-- ---------- toast ----------
	local toastHost = Instance.new("Frame", gui)
	toastHost.Size = UDim2.new(0, 240, 1, -20); toastHost.Position = UDim2.new(0.5, -120, 0, 8)
	toastHost.BackgroundTransparency = 1; toastHost.ZIndex = 900
	local tl = Instance.new("UIListLayout", toastHost)
	tl.Padding = UDim.new(0, 5); tl.SortOrder = Enum.SortOrder.LayoutOrder
	lib.Notify = function(title, text, dur)
		pcall(function()
			local f = Instance.new("Frame", toastHost)
			f.Size = UDim2.new(1, 0, 0, 46); f.BackgroundColor3 = C.BG; f.BackgroundTransparency = 0.1
			f.BorderSizePixel = 0; f.ZIndex = 901
			corner(f, 10); addLivingStroke(f, 1)
			local tbar = Instance.new("Frame", f)
			tbar.Size = UDim2.new(0, 3, 1, -12); tbar.Position = UDim2.new(0, 0, 0, 6)
			tbar.BackgroundColor3 = C.MOON2; tbar.BorderSizePixel = 0; tbar.ZIndex = 902
			corner(tbar, 2)
			local tsc = Instance.new("UIScale", f); tsc.Scale = 0.9
			TweenService:Create(tsc, TweenInfo.new(0.22, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = 1}):Play()
			local t = label(f, tostring(title or ""), UDim2.new(1, -20, 0, 16), C.WHITE, Enum.Font.GothamBold)
			t.Position = UDim2.new(0, 14, 0, 5); t.TextSize = 11; t.ZIndex = 902; liveGrad(t)
			local d = label(f, tostring(text or ""), UDim2.new(1, -20, 0, 22), C.SILVER, Enum.Font.GothamMedium)
			d.Position = UDim2.new(0, 14, 0, 21); d.TextSize = 9.5; d.TextWrapped = true
			d.TextYAlignment = Enum.TextYAlignment.Top; d.ZIndex = 902
			task.delay(tonumber(dur) or 4, function() pcall(function() f:Destroy() end) end)
		end)
	end

	-- ---------- badge: a small semi-transparent pill pinned under the top bar ----------
	local bannerToken = 0
	lib.Banner = function(text, dur)
		pcall(function()
			bannerToken = bannerToken + 1
			local mine = bannerToken
			local old = gui:FindFirstChild("SourcesHubBanner")
			if old then old:Destroy() end
			local f = Instance.new("TextLabel", gui)
			f.Name = "SourcesHubBanner"
			f.AnchorPoint = Vector2.new(0.5, 0)
			f.Position = UDim2.new(0.5, 0, 0, 42)
			f.Size = UDim2.new(0, 0, 0, 24); f.AutomaticSize = Enum.AutomaticSize.X
			f.BackgroundColor3 = C.BG; f.BackgroundTransparency = 0.35
			f.BorderSizePixel = 0; f.ZIndex = 920
			f.Text = tostring(text or ""); f.Font = Enum.Font.GothamBold; f.TextSize = 10
			f.TextColor3 = C.WHITE; styleText(f)
			local pad = Instance.new("UIPadding", f)
			pad.PaddingLeft = UDim.new(0, 12); pad.PaddingRight = UDim.new(0, 12)
			corner(f, 12); addLivingStroke(f, 1.2); liveGrad(f)
			local sc = Instance.new("UIScale", f); sc.Scale = 0.85
			TweenService:Create(sc, TweenInfo.new(0.25, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = 1}):Play()
			task.delay(tonumber(dur) or 5, function()
				if bannerToken == mine and f.Parent then
					TweenService:Create(f, TweenInfo.new(0.3), {BackgroundTransparency = 1, TextTransparency = 1}):Play()
					task.delay(0.3, function() pcall(function() f:Destroy() end) end)
				end
			end)
		end)
	end

	lib.GuideSeen = function() return store["GuideSeen"] == true end
	lib.MarkGuideSeen = function() setStored("GuideSeen", true) end
	lib.ThemeNames = TH.names
	lib.ThemeName = TH.current
	lib.SetTheme = function(name)
		if not TH.sets[name] or name == TH.current then return end
		local list = TH.pairsFor(TH.current, name)
		TH.current = name; lib.ThemeName = name
		TH.apply(name)
		TH.recolor(gui, list)
		TH.runHooks(list)
		setStored("Theme", name)
	end
	lib.ThemeHooks = TH.hooks
	lib.RunThemeHooksFrom = function(fromName)
		if TH.sets[fromName] and fromName ~= TH.current then TH.runHooks(TH.pairsFor(fromName, TH.current)) end
	end

	lib.SoundOn = true
	-- UI Optimizer: stops the shimmer sweeps and makes every interface tween instant
	lib.NoAnim = false
	lib.SetNoAnim = function(on)
		on = on == true
		lib.NoAnim = on
		lib.AnimUser = not on
		if on then
			for k = 1, #_sweep do
				local g = _sweep[k]
				if g.Parent then g.Offset = Vector2.new(0, 0) end
			end
		end
	end
	local sounds = {}
	lib.Sound = function(kind)
		if lib.SoundOn == false or not lib.ParticlesOn then return end
		pcall(function()
			local snd = sounds[kind]
			if not snd or not snd.Parent then
				snd = Instance.new("Sound")
				snd.Volume = kind == "click" and 0.25 or 0.35
				snd.SoundId = kind == "click" and "rbxasset://sounds/switch.wav" or "rbxasset://sounds/electronicpingshort.wav"
				snd.PlaybackSpeed = kind == "close" and 0.8 or (kind == "open" and 1.15 or 1)
				snd.Parent = gui
				sounds[kind] = snd
			end
			snd:Play()
		end)
	end

	-- ---------- risk badge: centered, red blinking stroke, gone after a few seconds ----------
	local riskToken = 0
	lib.RiskBadge = function(title, text, dur)
		pcall(function()
			riskToken = riskToken + 1
			local mine = riskToken
			local old = gui:FindFirstChild("SourcesHubRisk")
			if old then old:Destroy() end
			local f = Instance.new("Frame", gui)
			f.Name = "SourcesHubRisk"
			f.AnchorPoint = Vector2.new(0.5, 0.5); f.Position = UDim2.new(0.5, 0, 0.5, 0)
			f.Size = UDim2.new(0, 300, 0, 92)
			f.BackgroundColor3 = C.BG; f.BackgroundTransparency = 0.25
			f.BorderSizePixel = 0; f.ZIndex = 930
			corner(f, 14)
			local st = Instance.new("UIStroke", f)
			st.Color = C.RED; st.Thickness = 2.5; st.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
			local t = label(f, tostring(title or ""), UDim2.new(1, -20, 0, 18), C.RED, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
			t.Position = UDim2.new(0, 10, 0, 8); t.TextSize = 12; t.ZIndex = 931
			local d = label(f, tostring(text or ""), UDim2.new(1, -24, 0, 56), C.SILVER, Enum.Font.GothamMedium, Enum.TextXAlignment.Center)
			d.Position = UDim2.new(0, 12, 0, 28); d.TextSize = 10; d.TextWrapped = true
			d.TextYAlignment = Enum.TextYAlignment.Top; d.ZIndex = 931
			local sc = Instance.new("UIScale", f); sc.Scale = 0.85
			TweenService:Create(sc, TweenInfo.new(0.25, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = 1}):Play()
			local endAt = os.clock() + (tonumber(dur) or 10)
			task.spawn(function()
				local dim = false
				while riskToken == mine and f.Parent and os.clock() < endAt do
					dim = not dim
					TweenService:Create(st, TweenInfo.new(0.3, Enum.EasingStyle.Sine), {Transparency = dim and 0.85 or 0}):Play()
					task.wait(0.3)
				end
				if riskToken == mine and f.Parent then
					TweenService:Create(f, TweenInfo.new(0.3), {BackgroundTransparency = 1}):Play()
					TweenService:Create(st, TweenInfo.new(0.3), {Transparency = 1}):Play()
					TweenService:Create(t, TweenInfo.new(0.3), {TextTransparency = 1}):Play()
					TweenService:Create(d, TweenInfo.new(0.3), {TextTransparency = 1}):Play()
					task.wait(0.35)
					pcall(function() f:Destroy() end)
				end
			end)
		end)
	end

	-- ---------- startup splash: what loaded and what did not ----------
	lib.Splash = function(lines)
		pcall(function()
			local rowH = 17
			local H = 54 + #lines * rowH
			local f = Instance.new("Frame", gui)
			f.Name = "SourcesHubSplash"
			f.AnchorPoint = Vector2.new(0.5, 0.5)
			f.Position = UDim2.new(0.5, 0, 0.5, 0)
			f.Size = UDim2.new(0, 258, 0, H)
			f.BackgroundColor3 = C.BG; f.BorderSizePixel = 0; f.ZIndex = 950
			corner(f, 18); addLivingStroke(f, 1.5, true)
			local sc = Instance.new("UIScale", f); sc.Scale = 0.8
			local bad = 0
			for _, ln in ipairs(lines) do if ln.Ok == false then bad = bad + 1 end end
			local t = label(f, "Sources Hub", UDim2.new(1, -24, 0, 22), C.WHITE, Enum.Font.GothamBold)
			t.Position = UDim2.new(0, 14, 0, 8); t.TextSize = 15; t.ZIndex = 951; liveGrad(t)
			local sub = label(f, bad == 0 and "Everything loaded" or (bad .. " problem" .. (bad > 1 and "s" or "") .. " found"),
				UDim2.new(1, -24, 0, 12), bad == 0 and C.GREEN or C.GOLD, Enum.Font.GothamMedium)
			sub.Position = UDim2.new(0, 14, 0, 30); sub.TextSize = 9.5; sub.ZIndex = 951
			for i, ln in ipairs(lines) do
				local y = 50 + (i - 1) * rowH
				local dot = Instance.new("Frame", f)
				dot.Size = UDim2.new(0, 7, 0, 7); dot.Position = UDim2.new(0, 16, 0, y + 5)
				dot.BackgroundColor3 = ln.Ok and C.GREEN or C.RED; dot.BorderSizePixel = 0; dot.ZIndex = 951
				corner(dot, 4)
				local tx = label(f, ln.Text, UDim2.new(1, -40, 0, rowH), ln.Ok and C.SILVER or C.GOLD, Enum.Font.GothamMedium)
				tx.Position = UDim2.new(0, 30, 0, y); tx.TextSize = 9.5; tx.ZIndex = 951
				tx.TextTruncate = Enum.TextTruncate.AtEnd
			end
			TweenService:Create(sc, TweenInfo.new(0.35, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = 1}):Play()
			task.delay(bad == 0 and 3.5 or 7, function()
				if f.Parent then
					TweenService:Create(sc, TweenInfo.new(0.25, Enum.EasingStyle.Quad, Enum.EasingDirection.In), {Scale = 0.85}):Play()
					task.delay(0.26, function() pcall(function() f:Destroy() end) end)
				end
			end)
		end)
	end

	-- ---------- window ----------
	local windows = {}

	-- sidebar order and little drawn icons (no external images needed)
	local TAB_ORDER = {Farm = 1, StealPanel = 2, Events = 3, Config = 999}
	
	local function newWindow(cfg)
		local w = {tabs = {}, order = {}, current = nil, name = cfg.name, isMain = cfg.isMain == true, newLook = true}
		local vp = workspace.CurrentCamera and workspace.CurrentCamera.ViewportSize or Vector2.new(800, 600)
		local H = math.min(cfg.h, math.max(240, vp.Y - 60))
		local frame = Instance.new("Frame", gui)
		frame.Name = cfg.frameName
		frame.Size = UDim2.new(0, cfg.w, 0, H)
		frame.Position = cfg.pos
		frame.BackgroundColor3 = C.BG
		frame.BorderSizePixel = 0
		frame.ClipsDescendants = true
		frame.Active = true
		frame.ZIndex = cfg.z or 20
		corner(frame, 8)
		addLivingStroke(frame, 1.5, true, true)
		local winScale = Instance.new("UIScale", frame)
		w.frame = frame

		local bgImg, subtitle
		do
			bgImg = Instance.new("ImageLabel", frame)
			bgImg.Name = "Bg"
			bgImg.BackgroundTransparency = 1; bgImg.BorderSizePixel = 0
			bgImg.Image = "rbxassetid://111331179075915"
			bgImg.ScaleType = Enum.ScaleType.Fit
			bgImg.ImageTransparency = 0.88
			bgImg.AnchorPoint = Vector2.new(0.5, 0.5)
			bgImg.Position = UDim2.new(0.5, 0, 0.56, 0)
			local bgSize = math.floor(math.min(cfg.w, H) * 0.86)
			bgImg.Size = UDim2.fromOffset(bgSize, bgSize)
			bgImg.ZIndex = 1
		end
		local veil
		if cfg.isMain then
			veil = Instance.new("Frame", frame)
			veil.Name = "Veil"; veil.Size = UDim2.new(1, 0, 1, 0)
			veil.BackgroundColor3 = C.BG; veil.BackgroundTransparency = 1; veil.BorderSizePixel = 0; veil.ZIndex = 900
			corner(veil, 8)
		end

		local header, moon, title, close, mini, sep, tabBar, content, footerRight
		local contentX, bodyTopV = 0, 46
		local footerH = cfg.isMain and 20 or 0
		do
			header = Instance.new("Frame", frame)
			header.Size = UDim2.new(1, 0, 0, 42)
			header.BackgroundColor3 = C.HEADER; header.BorderSizePixel = 0
			corner(header, 8)
			local SW = math.clamp(cfg.w - 40 - 110 - 72, 96, 140)
			moon = Instance.new("ImageLabel", header)
			moon.Size = UDim2.new(0, 24, 0, 24); moon.Position = UDim2.new(0, 9, 0.5, -12)
			moon.BackgroundTransparency = 1; moon.BorderSizePixel = 0
			moon.Image = "rbxassetid://111331179075915"
			moon.ScaleType = Enum.ScaleType.Fit
			title = Instance.new("TextLabel", header)
			title.BackgroundTransparency = 1
			title.Text = cfg.title; title.TextSize = 14; title.Font = Enum.Font.GothamBold
			title.TextXAlignment = Enum.TextXAlignment.Left; title.TextColor3 = C.WHITE
			title.TextTruncate = Enum.TextTruncate.AtEnd
			if cfg.subtitle then
				title.Size = UDim2.new(1, -(SW + 116), 0, 20); title.Position = UDim2.new(0, 40, 0, 4)
				subtitle = label(header, tostring(cfg.subtitle), UDim2.new(1, -(SW + 116), 0, 12), C.DIM, Enum.Font.GothamMedium)
				subtitle.Position = UDim2.new(0, 40, 0, 25); subtitle.TextSize = 9; subtitle.TextTruncate = Enum.TextTruncate.AtEnd
				if cfg.subtitleCopy then
					subtitle.TextColor3 = C.MOON2
					local sb = Instance.new("TextButton", subtitle)
					sb.Size = UDim2.new(1, 0, 1, 0); sb.BackgroundTransparency = 1; sb.Text = ""
					sb.MouseButton1Click:Connect(function()
						pcall(function() setclipboard(cfg.subtitleCopy) end)
						if lib.Notify then lib.Notify("Discord", "Link copied: " .. cfg.subtitleCopy, 2.5) end
					end)
				end
			else
				title.Size = UDim2.new(1, -(SW + 116), 1, 0); title.Position = UDim2.new(0, 40, 0, 0)
			end
			liveGrad(title, true, true)
			close = Instance.new("TextButton", header)
			close.Size = UDim2.new(0, 22, 0, 22); close.Position = UDim2.new(1, -30, 0.5, -11)
			close.BackgroundColor3 = Color3.fromRGB(58, 20, 20); close.Text = "X"; close.TextSize = 11
			close.TextColor3 = C.RED; close.Font = Enum.Font.GothamBold; close.BorderSizePixel = 0
			corner(close, 6); addLivingStroke(close, 1); pressFx(close)
			mini = Instance.new("TextButton", header)
			mini.Size = UDim2.new(0, 22, 0, 22); mini.Position = UDim2.new(1, -56, 0.5, -11)
			mini.BackgroundColor3 = Color3.fromRGB(24, 26, 35); mini.Text = "-"; mini.TextSize = 13
			mini.TextColor3 = C.ACCENT2; mini.Font = Enum.Font.GothamBold; mini.BorderSizePixel = 0
			corner(mini, 6); addLivingStroke(mini, 1); pressFx(mini)
			local SH = 24
			local bar = Instance.new("Frame", header)
			bar.Name = "SearchBar"; bar.ZIndex = 50
			bar.Size = UDim2.new(0, SW, 0, SH); bar.Position = UDim2.new(1, -(56 + 8 + SW), 0.5, -SH / 2)
			bar.BackgroundColor3 = Color3.fromRGB(34, 8, 10); bar.BorderSizePixel = 0
			corner(bar, 12); addLivingStroke(bar, 1.3, true, true)
			local lens = Instance.new("Frame", bar)
			lens.ZIndex = 51; lens.Size = UDim2.fromOffset(9, 9); lens.Position = UDim2.new(0, 8, 0.5, -6)
			lens.BackgroundTransparency = 1; lens.BorderSizePixel = 0
			corner(lens, 5); stroke(lens, C.MOON2, 1.5)
			local handle = Instance.new("Frame", bar)
			handle.ZIndex = 51; handle.Size = UDim2.fromOffset(5, 2); handle.Position = UDim2.new(0, 15, 0.5, 3)
			handle.Rotation = 45; handle.BackgroundColor3 = C.MOON2; handle.BorderSizePixel = 0
			local search = Instance.new("TextBox", bar)
			search.Name = "Search"; search.ZIndex = 52
			search.Size = UDim2.new(1, -30, 1, 0); search.Position = UDim2.new(0, 24, 0, 0)
			search.BackgroundTransparency = 1; search.BorderSizePixel = 0
			search.PlaceholderText = "Search..."; search.PlaceholderColor3 = Color3.fromRGB(200, 150, 150)
			search.Text = ""; search.TextColor3 = Color3.fromRGB(255, 255, 255); search.TextSize = 12; search.Font = Enum.Font.GothamBold
			search.ClearTextOnFocus = false; search.TextXAlignment = Enum.TextXAlignment.Left
			styleText(search)
			search.ClipsDescendants = true
			search:GetPropertyChangedSignal("Text"):Connect(function() if w.ApplyFilter then w.ApplyFilter(search.Text) end end)
			search.FocusLost:Connect(function()
				if w.ApplyFilter then w.ApplyFilter(search.Text) end
				TweenService:Create(bar, TweenInfo.new(0.2, Enum.EasingStyle.Quint, Enum.EasingDirection.Out), {
					Size = UDim2.new(0, SW, 0, SH), Position = UDim2.new(1, -(56 + 8 + SW), 0.5, -SH / 2)}):Play()
			end)
			search.Focused:Connect(function()
				TweenService:Create(bar, TweenInfo.new(0.2, Enum.EasingStyle.Quint, Enum.EasingDirection.Out), {
					Size = UDim2.new(0, SW + 30, 0, SH), Position = UDim2.new(1, -(56 + 8 + SW + 30), 0.5, -SH / 2)}):Play()
			end)
			w.search = bar
			w.searchBox = search
			sep = Instance.new("Frame", frame)
			sep.Size = UDim2.new(1, 0, 0, 2); sep.Position = UDim2.new(0, 0, 0, 42)
			sep.BackgroundColor3 = C.WHITE; sep.BorderSizePixel = 0
			liveGrad(sep, true, true)

			if not cfg.noTabs then
				contentX = 108
				tabBar = Instance.new("ScrollingFrame", frame)
				tabBar.Name = "SideTabs"
				tabBar.Size = UDim2.new(0, contentX, 1, -(44 + footerH)); tabBar.Position = UDim2.new(0, 0, 0, 44)
				tabBar.BackgroundColor3 = C.ROW; tabBar.BackgroundTransparency = 0.45; tabBar.BorderSizePixel = 0
				tabBar.ScrollBarThickness = 0
				tabBar.CanvasSize = UDim2.new(0, 0, 0, 0)
				tabBar.AutomaticCanvasSize = Enum.AutomaticSize.Y
				tabBar.ScrollingDirection = Enum.ScrollingDirection.Y
				local tl2 = Instance.new("UIListLayout", tabBar)
				tl2.Padding = UDim.new(0, 3); tl2.SortOrder = Enum.SortOrder.LayoutOrder
				local tp2 = Instance.new("UIPadding", tabBar)
				tp2.PaddingTop = UDim.new(0, 6); tp2.PaddingLeft = UDim.new(0, 4); tp2.PaddingRight = UDim.new(0, 4)
				local sideLine = Instance.new("Frame", frame)
				sideLine.Name = "SideLine"
				sideLine.Size = UDim2.new(0, 1, 1, -(44 + footerH)); sideLine.Position = UDim2.new(0, contentX, 0, 44)
				sideLine.BackgroundColor3 = C.WHITE; sideLine.BorderSizePixel = 0
				liveGrad(sideLine, true, true)
				w.sideLine = sideLine
				w.tabBar = tabBar
			end
			content = Instance.new("Frame", frame)
			content.Size = UDim2.new(1, -contentX, 1, -(46 + footerH)); content.Position = UDim2.new(0, contentX, 0, 46)
			content.BackgroundTransparency = 1; content.ClipsDescendants = true
			w.content = content
			if content.DescendantAdded then
				content.DescendantAdded:Connect(function(d)
					if d:IsA("TextLabel") or d:IsA("TextButton") or d:IsA("TextBox") then
						task.defer(function()
							if d.Parent and d.Text ~= "" then styleText(d) end
						end)
					end
				end)
			end

			local footer = Instance.new("Frame", frame)
			footer.Name = "Footer"
			footer.Size = UDim2.new(1, 0, 0, footerH); footer.Position = UDim2.new(0, 0, 1, -footerH)
			footer.BackgroundColor3 = C.HEADER; footer.BackgroundTransparency = 0.1; footer.BorderSizePixel = 0
			local fline = Instance.new("Frame", footer)
			fline.Size = UDim2.new(1, 0, 0, 1); fline.BackgroundColor3 = C.WHITE; fline.BorderSizePixel = 0
			liveGrad(fline, true, true)
			local fl = label(footer, "RightShift to hide", UDim2.new(0.5, -10, 1, 0), C.DIM, Enum.Font.GothamMedium)
			fl.Position = UDim2.new(0, 10, 0, 0); fl.TextSize = 8.5
			footerRight = label(footer, "60 FPS   0 ms", UDim2.new(0.5, -10, 1, 0), C.MOON2, Enum.Font.GothamBold, Enum.TextXAlignment.Right)
			footerRight.Position = UDim2.new(0.5, 0, 0, 0); footerRight.TextSize = 8.5
			w.footer = footer

			local noRes = label(content, "No matching feature", UDim2.new(1, 0, 0, 30), C.DIM, Enum.Font.GothamMedium, Enum.TextXAlignment.Center)
			noRes.Position = UDim2.new(0, 0, 0, 40); noRes.TextSize = 11; noRes.Visible = false; noRes.ZIndex = 5
			w.noResults = noRes

			local pageVeil = Instance.new("Frame", content)
			pageVeil.Name = "PageVeil"; pageVeil.Size = UDim2.new(1, 0, 1, 0)
			pageVeil.BackgroundColor3 = C.BG; pageVeil.BackgroundTransparency = 1; pageVeil.BorderSizePixel = 0; pageVeil.ZIndex = 150
			local sweep = Instance.new("Frame", content)
			sweep.Name = "PageSweep"; sweep.Size = UDim2.new(0.4, 0, 0, 2); sweep.Position = UDim2.new(-0.4, 0, 0, 0)
			sweep.BackgroundColor3 = C.WHITE; sweep.BorderSizePixel = 0; sweep.ZIndex = 151; sweep.Visible = false
			local sg = Instance.new("UIGradient", sweep)
			sg.Color = ColorSequence.new({
				ColorSequenceKeypoint.new(0, C.DEEP1), ColorSequenceKeypoint.new(0.5, C.MOON2), ColorSequenceKeypoint.new(1, C.DEEP1)})
			w.Transition = function()
				if lib.NoAnim then return end
				pageVeil.BackgroundTransparency = 0.4
				TweenService:Create(pageVeil, TweenInfo.new(0.34, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {BackgroundTransparency = 1}):Play()
				sweep.Position = UDim2.new(-0.4, 0, 0, 0); sweep.Visible = true
				TweenService:Create(sweep, TweenInfo.new(0.38, Enum.EasingStyle.Quint, Enum.EasingDirection.Out), {Position = UDim2.new(1, 0, 0, 0)}):Play()
				task.delay(0.4, function() sweep.Visible = false end)
			end
		end

		-- picker overlay (single / multi select) covering the content area
		local ov = Instance.new("Frame", frame)
		ov.Size = UDim2.new(1, -contentX, 1, -(bodyTopV + footerH)); ov.Position = UDim2.new(0, contentX, 0, bodyTopV)
		ov.BackgroundColor3 = C.BG; ov.BorderSizePixel = 0; ov.Visible = false; ov.ZIndex = 300
		local ovHead = Instance.new("Frame", ov)
		ovHead.Size = UDim2.new(1, 0, 0, 26); ovHead.BackgroundTransparency = 1; ovHead.ZIndex = 301
		local ovTitle = label(ovHead, "", UDim2.new(1, -120, 1, 0), C.WHITE, Enum.Font.GothamBold)
		ovTitle.Position = UDim2.new(0, 8, 0, 0); ovTitle.TextSize = 11.5; ovTitle.ZIndex = 301
		local ovClear = Instance.new("TextButton", ovHead)
		ovClear.Size = UDim2.new(0, 46, 0, 20); ovClear.Position = UDim2.new(1, -104, 0, 3)
		ovClear.BackgroundColor3 = Color3.fromRGB(24, 26, 35); ovClear.Text = "Clear"; ovClear.TextSize = 10
		ovClear.TextColor3 = C.SILVER; ovClear.Font = Enum.Font.GothamBold; ovClear.BorderSizePixel = 0; ovClear.ZIndex = 301
		styleText(ovClear)
		corner(ovClear, 8); addLivingStroke(ovClear, 1); pressFx(ovClear)
		local ovDone = Instance.new("TextButton", ovHead)
		ovDone.Size = UDim2.new(0, 46, 0, 20); ovDone.Position = UDim2.new(1, -54, 0, 3)
		ovDone.BackgroundColor3 = C.MOON; ovDone.Text = "Done"; ovDone.TextSize = 10.5
		ovDone.TextColor3 = C.MOONTEXT; ovDone.Font = Enum.Font.GothamBold; ovDone.BorderSizePixel = 0; ovDone.ZIndex = 301
		corner(ovDone, 8); addLivingStroke(ovDone, 1); pressFx(ovDone)
		local ovList = Instance.new("ScrollingFrame", ov)
		ovList.Size = UDim2.new(1, 0, 1, -30); ovList.Position = UDim2.new(0, 0, 0, 28)
		ovList.BackgroundTransparency = 1; ovList.BorderSizePixel = 0; ovList.ScrollBarThickness = 3
		ovList.ScrollBarImageColor3 = C.ACCENT; ovList.CanvasSize = UDim2.new(0, 0, 0, 0)
		ovList.AutomaticCanvasSize = Enum.AutomaticSize.Y; ovList.ZIndex = 301
		local ovl = Instance.new("UIListLayout", ovList)
		ovl.Padding = UDim.new(0, 3); ovl.SortOrder = Enum.SortOrder.LayoutOrder
		local ovp = Instance.new("UIPadding", ovList)
		ovp.PaddingLeft = UDim.new(0, 8); ovp.PaddingRight = UDim.new(0, 8); ovp.PaddingTop = UDim.new(0, 4)
		ovDone.MouseButton1Click:Connect(function() ov.Visible = false end)
		local clearFn
		ovClear.MouseButton1Click:Connect(function() if clearFn then clearFn() end end)

		-- opts: {title, options, multi, isOn(opt), toggle(opt), onClear}
		function w.Pick(opts)
			ovTitle.Text = opts.title
			for _, c in ipairs(ovList:GetChildren()) do if c:IsA("Frame") then c:Destroy() end end
			ovClear.Visible = opts.multi == true
			local marks, rowsOf = {}, {}
			local function refreshMarks()
				for opt, m in pairs(marks) do
					local on = opts.isOn(opt)
					m.BackgroundColor3 = on and C.MOON or Color3.fromRGB(10, 14, 22)
					local rr = rowsOf[opt]
					if rr then
						rr.row.BackgroundColor3 = on and C.ON_BG or C.ROW
						rr.edge.BackgroundTransparency = on and 0 or 1
					end
				end
			end
			clearFn = function() if opts.onClear then opts.onClear() end; refreshMarks() end
			for i, opt in ipairs(opts.options) do
				local r = Instance.new("Frame", ovList)
				r.Size = UDim2.new(1, 0, 0, 30); r.BackgroundColor3 = C.ROW; r.BackgroundTransparency = 0.15
				r.BorderSizePixel = 0; r.ZIndex = 301; r.LayoutOrder = i
				corner(r, 8); addLivingStroke(r, 1)
				local edge = Instance.new("Frame", r)
				edge.Size = UDim2.new(0, 3, 1, -10); edge.Position = UDim2.new(0, 0, 0, 5)
				edge.BackgroundColor3 = C.MOON2; edge.BackgroundTransparency = 1; edge.BorderSizePixel = 0; edge.ZIndex = 302
				corner(edge, 2)
				rowsOf[opt] = {row = r, edge = edge}
				local off = 12
				local ic = iconOf(opt)
				if ic then
					local img = Instance.new("ImageLabel", r)
					img.Size = UDim2.fromOffset(22, 22); img.Position = UDim2.new(0, 8, 0.5, -11)
					img.BackgroundTransparency = 1; img.Image = ic; img.ZIndex = 302
					off = 36
				end
				local ol = label(r, tostring(opt), UDim2.new(1, -off - 38, 1, 0), C.WHITE, Enum.Font.GothamMedium)
				ol.Position = UDim2.new(0, off, 0, 0); ol.TextSize = 11; ol.ZIndex = 302
				ol.TextTruncate = Enum.TextTruncate.AtEnd
				local mark = Instance.new("Frame", r)
				mark.Size = UDim2.new(0, 18, 0, 18); mark.Position = UDim2.new(1, -28, 0.5, -9)
				mark.BorderSizePixel = 0; mark.ZIndex = 302
				corner(mark, opts.multi and 5 or 9); addLivingStroke(mark, 1)
				marks[opt] = mark
				local b = Instance.new("TextButton", r)
				b.Size = UDim2.new(1, 0, 1, 0); b.BackgroundTransparency = 1; b.Text = ""; b.ZIndex = 303
				b.MouseButton1Click:Connect(function()
					opts.toggle(opt)
					if opts.multi then refreshMarks() else ov.Visible = false end
				end)
			end
			refreshMarks()
			ov.Visible = true
		end

		-- minimize / close / drag
		local minimized, fullH = false, H
		local hudFps, hudPing, hudLabel, hudHint = 60, 0, nil, nil
		if cfg.isMain then
			local acc, frames = 0, 0
			RunService.RenderStepped:Connect(function(dt)
				acc = acc + dt; frames = frames + 1
				if acc >= 0.5 then
						hudFps = math.floor(frames / acc + 0.5); acc = 0; frames = 0
						lib.T0 = lib.T0 or os.clock()
						if os.clock() - lib.T0 > 6 then lib.PeakFps = math.max(lib.PeakFps or 0, hudFps) end
						local ref = lib.RefFps or 60

						if lib.PeakFps then
							for _, candidate in ipairs({ 30, 60, 90, 120, 144, 165, 240 }) do
								ref = candidate
								if candidate >= lib.PeakFps * 0.92 then break end
							end
						end

						if lib.RefFps ~= ref then
							lib.RefFps = ref
							if lib.OnRefFps then pcall(lib.OnRefFps, ref) end
						end
						local lowT, highT = (lib.RefFps or 60) * 0.58, (lib.RefFps or 60) * 0.75
						if hudFps < lowT then lib.AnimAuto = false elseif hudFps >= highT then lib.AnimAuto = true end
					end
			end)
			hudLabel = label(header, "", UDim2.new(1, -44, 0, 20), C.WHITE, Enum.Font.GothamBold, Enum.TextXAlignment.Left)
			hudLabel.Position = UDim2.new(0, 38, 0, 4); hudLabel.TextSize = 13; hudLabel.Visible = false
			liveGrad(hudLabel, true)
			hudHint = label(header, "tap to open", UDim2.new(1, -44, 0, 12), C.SILVER, Enum.Font.GothamBold, Enum.TextXAlignment.Left)
			hudHint.Position = UDim2.new(0, 38, 0, 24); hudHint.TextSize = 8.5; hudHint.Visible = false
			local tripStroke = Instance.new("UIStroke", frame)
			tripStroke.Thickness = 2.5; tripStroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
			tripStroke.Color = C.MOON2; tripStroke.Enabled = false
			local tripGrad = Instance.new("UIGradient", tripStroke)
			task.spawn(function()
				while frame.Parent do
					task.wait(0.2)
					local prog, kind = nil, nil
					if minimized and lib.TripStatus then
						local ok, a, b = pcall(lib.TripStatus)
						if ok then prog, kind = a, b end
					end
					if prog then
						prog = math.clamp(prog, 0.02, 0.99)
						tripGrad.Transparency = NumberSequence.new({
							NumberSequenceKeypoint.new(0, 0), NumberSequenceKeypoint.new(prog, 0),
							NumberSequenceKeypoint.new(math.min(prog + 0.002, 0.999), 1), NumberSequenceKeypoint.new(1, 1)})
						tripStroke.Color = kind == "fail" and C.RED or (kind == "done" and C.GREEN or C.MOON2)
						tripStroke.Enabled = true
					else
						tripStroke.Enabled = false
					end
				end
			end)
			task.spawn(function()
				while frame.Parent do
					task.wait(0.5)
					pcall(function()
						hudPing = math.floor(game:GetService("Stats").Network.ServerStatsItem["Data Ping"]:GetValue() + 0.5)
					end)
					if footerRight then footerRight.Text = hudFps .. " FPS   " .. hudPing .. " ms" end
					if minimized then
						hudLabel.Text = hudFps .. " FPS   " .. hudPing .. " ms"
					end
				end
			end)
		end
		local arrowBtn
		local function updateArrow()
			if arrowBtn then arrowBtn.Visible = minimized and w.wantOpen ~= false end
		end
		if not cfg.isMain then
			local tray = gui:FindFirstChild("PanelTray")
			if not tray then
				tray = Instance.new("Frame", gui)
				tray.Name = "PanelTray"; tray.BackgroundTransparency = 1
				tray.AnchorPoint = Vector2.new(0.5, 0); tray.Position = UDim2.new(0.5, 0, 0, 4)
				tray.Size = UDim2.new(0, 0, 0, 30); tray.AutomaticSize = Enum.AutomaticSize.X
				tray.ZIndex = 400
				local tl = Instance.new("UIListLayout", tray)
				tl.FillDirection = Enum.FillDirection.Horizontal; tl.Padding = UDim.new(0, 8)
				tl.HorizontalAlignment = Enum.HorizontalAlignment.Center
				tl.VerticalAlignment = Enum.VerticalAlignment.Center
			end
			arrowBtn = Instance.new("TextButton", tray)
			arrowBtn.Size = UDim2.new(0, 0, 0, 28); arrowBtn.AutomaticSize = Enum.AutomaticSize.X
			arrowBtn.AutoButtonColor = false
			arrowBtn.BackgroundColor3 = C.ROW; arrowBtn.BackgroundTransparency = 0.2
			arrowBtn.Text = "v  " .. string.upper(tostring(cfg.title or "")); arrowBtn.Font = Enum.Font.GothamBold; arrowBtn.TextSize = 12
			arrowBtn.TextColor3 = C.WHITE; arrowBtn.ZIndex = 401; arrowBtn.Visible = false
			local ap = Instance.new("UIPadding", arrowBtn)
			ap.PaddingLeft = UDim.new(0, 14); ap.PaddingRight = UDim.new(0, 14)
			corner(arrowBtn, 14); addLivingStroke(arrowBtn, 1.5); liveGrad(arrowBtn)
			arrowBtn.MouseButton1Click:Connect(function() w.SetMinimized(false) end)
		end
		-- dust forge: the panel builds itself from small stroked tiles and dust, and folds back into the top bar
		local forgeToken = 0
		local function forge(mode)
			forgeToken = forgeToken + 1
			local mine = forgeToken
			local old = gui:FindFirstChild("Forge_" .. tostring(cfg.name))
			if old then old:Destroy() end

			if mode == "in" then frame.Visible = true; updateArrow() end
			local scr = gui.AbsoluteSize
			local fp = frame.Position
			local margin = 5
			local pos = Vector2.new(fp.X.Scale * scr.X + fp.X.Offset - margin, fp.Y.Scale * scr.Y + fp.Y.Offset - margin)
			local size = Vector2.new(cfg.w + margin * 2, fullH + margin * 2)

			if size.X < 20 or size.Y < 20 then
				frame.Visible = mode == "in"
				updateArrow()
				return
			end
			local box = Instance.new("Folder", gui)
			box.Name = "Forge_" .. tostring(cfg.name)
			local cols = 6
			local tw = size.X / cols
			local rows = math.max(5, math.floor(size.Y / tw + 0.5))
			local th = size.Y / rows
			local center = pos + size / 2
			local maxDist = (size / 2).Magnitude
			local tiles = {}

			for r = 0, rows - 1 do
				for c = 0, cols - 1 do
					local tile = Instance.new("Frame", box)
					tile.BorderSizePixel = 0
					tile.BackgroundColor3 = C.BG
					tile.ZIndex = 800
					tile.AnchorPoint = Vector2.new(0.5, 0.5)
					tile.Size = UDim2.fromOffset(tw + 1, th + 1)
					local home = pos + Vector2.new((c + 0.5) * tw, (r + 0.5) * th)
					tile.Position = UDim2.fromOffset(home.X, home.Y)
					local ts = Instance.new("UIStroke", tile)
					ts.Color = C.DEEP4; ts.Thickness = 1; ts.Transparency = 0.2
					tiles[#tiles + 1] = {Frame = tile, Stroke = ts, Home = home, Delay = (home - center).Magnitude / maxDist}
				end
			end

			local function dust(count, fromOutside)
				for i = 1, count do
					local d = Instance.new("Frame", box)
					d.Size = UDim2.fromOffset(3, 3); d.AnchorPoint = Vector2.new(0.5, 0.5)
					d.BorderSizePixel = 0; d.ZIndex = 801
					d.BackgroundColor3 = i % 2 == 0 and C.MOON2 or C.DEEP4
					local inside = Vector2.new(pos.X + math.random() * size.X, pos.Y + math.random() * size.Y)
					local outside = inside + Vector2.new(math.random(-90, 90), math.random(-90, 90))
					local a, b = inside, outside
					if fromOutside then a, b = outside, inside end
					d.Position = UDim2.fromOffset(a.X, a.Y)
					d.BackgroundTransparency = fromOutside and 0.2 or 0.6
					TweenService:Create(d, TweenInfo.new(0.5 + math.random() * 0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
						Position = UDim2.fromOffset(b.X, b.Y), BackgroundTransparency = fromOutside and 0.9 or 1}):Play()
				end
			end

			if mode == "in" then
				dust(18, true)

				for _, t in ipairs(tiles) do
					task.delay(t.Delay * 0.45 + math.random() * 0.1, function()
						if forgeToken ~= mine then return end
						TweenService:Create(t.Frame, TweenInfo.new(0.26, Enum.EasingStyle.Quad), {
							BackgroundTransparency = 1, Size = UDim2.fromOffset(tw * 0.35, th * 0.35)}):Play()
						TweenService:Create(t.Stroke, TweenInfo.new(0.26), {Transparency = 1}):Play()
					end)
				end
				task.delay(0.95, function()
					if forgeToken == mine then box:Destroy() end
					updateArrow()
				end)
			else
				for _, t in ipairs(tiles) do
					t.Frame.BackgroundTransparency = 1
					t.Frame.Size = UDim2.fromOffset(tw * 0.35, th * 0.35)
					t.Stroke.Transparency = 1
					task.delay((1 - t.Delay) * 0.3 + math.random() * 0.08, function()
						if forgeToken ~= mine then return end
						TweenService:Create(t.Frame, TweenInfo.new(0.2, Enum.EasingStyle.Quad), {
							BackgroundTransparency = 0, Size = UDim2.fromOffset(tw + 1, th + 1)}):Play()
						TweenService:Create(t.Stroke, TweenInfo.new(0.2), {Transparency = 0.2}):Play()
					end)
				end
				dust(10, false)
				task.delay(0.5, function()
					if forgeToken ~= mine then return end
					frame.Visible = false
					local target = Vector2.new(gui.AbsoluteSize.X / 2, 18)

					for _, t in ipairs(tiles) do
						local jitter = Vector2.new(math.random(-40, 40), math.random(-6, 6))
						TweenService:Create(t.Frame, TweenInfo.new(0.45 + math.random() * 0.2, Enum.EasingStyle.Quint, Enum.EasingDirection.In), {
							Position = UDim2.fromOffset(target.X + jitter.X, target.Y + jitter.Y),
							Size = UDim2.fromOffset(4, 4), BackgroundTransparency = 0.6}):Play()
						TweenService:Create(t.Stroke, TweenInfo.new(0.5), {Transparency = 0.8}):Play()
					end
					task.delay(0.8, function()
						if forgeToken == mine then box:Destroy() end
						updateArrow()
					end)
				end)
			end
		end

		local function setMinimized(on)
			minimized = on
			if not cfg.isMain then
				if on then
					ov.Visible = false
					forge("out")
				else
					zTop = zTop + 1; frame.ZIndex = zTop
					winScale.Scale = 1
					mini.Text = "-"
					forge("in")
				end
				return
			end
			if cfg.isMain then
				if on then
					content.Visible = false; sep.Visible = false; ov.Visible = false
					if tabBar then tabBar.Visible = false end
					if w.sideLine then w.sideLine.Visible = false end
					title.Visible = false; mini.Visible = false; close.Visible = false; bgImg.Visible = false
					if w.footer then w.footer.Visible = false end
					if w.search then w.search.Visible = false end
					if subtitle then subtitle.Visible = false end
					hudLabel.Text = hudFps .. " FPS   " .. hudPing .. " ms"
					hudLabel.Visible = true; hudHint.Visible = true
					header.BackgroundTransparency = 1
					w.restorePos = frame.Position
					TweenService:Create(frame, TweenInfo.new(0.3, Enum.EasingStyle.Quint), {
						Size = UDim2.new(0, 168, 0, 42), Position = UDim2.new(0.5, -84, 0, 12), BackgroundTransparency = 0.12}):Play()
				else
					hudLabel.Visible = false; hudHint.Visible = false
					title.Visible = true; mini.Visible = true; close.Visible = true; bgImg.Visible = true
					if w.footer then w.footer.Visible = true end
					if w.search then w.search.Visible = true end
					if subtitle then subtitle.Visible = true end
					header.BackgroundTransparency = 0
					TweenService:Create(frame, TweenInfo.new(0.3, Enum.EasingStyle.Quint), {
						Size = UDim2.new(0, cfg.w, 0, fullH), Position = w.restorePos or cfg.pos, BackgroundTransparency = 0}):Play()
					content.Visible = true; sep.Visible = true
					if tabBar then tabBar.Visible = true end
					if w.sideLine then w.sideLine.Visible = true end
					mini.Text = "-"
				end
				return
			end
			if on then
				TweenService:Create(frame, TweenInfo.new(0.2), {Size = UDim2.new(0, cfg.w, 0, 42)}):Play()
				content.Visible = false; sep.Visible = false; ov.Visible = false
				if tabBar then tabBar.Visible = false end
					if w.sideLine then w.sideLine.Visible = false end
				mini.Text = "+"
			else
				TweenService:Create(frame, TweenInfo.new(0.2), {Size = UDim2.new(0, cfg.w, 0, fullH)}):Play()
				content.Visible = true; sep.Visible = true
				if tabBar then tabBar.Visible = true end
					if w.sideLine then w.sideLine.Visible = true end
				mini.Text = "-"
			end
		end
		w.SetMinimized = setMinimized
		
		mini.MouseButton1Click:Connect(function() setMinimized(not minimized) end)
		do
			local tapAt
			header.InputBegan:Connect(function(inp)
				if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then
					tapAt = inp.Position
				end
			end)
			header.InputEnded:Connect(function(inp)
				if minimized and tapAt and (inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch) then
					if (inp.Position - tapAt).Magnitude < 8 then setMinimized(false) end
					tapAt = nil
				end
			end)
		end
		w.OnClose = newSignalList()
		local closing = 0
		function w.SetOpen(on)
			on = on == true
			if lib.Sound and on ~= w.IsOpen() then lib.Sound(on and "open" or "close") end
			closing = closing + 1
			local mine = closing
			if on and minimized and not cfg.isMain then minimized = false; mini.Text = "-" end
			if on then
				zTop = zTop + 1; frame.ZIndex = zTop
				winScale.Scale = veil and 0.84 or 0.9
				frame.Visible = true
				if veil then
					veil.BackgroundTransparency = 0
					TweenService:Create(veil, TweenInfo.new(0.3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {BackgroundTransparency = 1}):Play()
				end
				TweenService:Create(winScale, TweenInfo.new(0.34, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {Scale = 1}):Play()
			elseif frame.Visible then
				if veil then
					TweenService:Create(veil, TweenInfo.new(0.2, Enum.EasingStyle.Quad, Enum.EasingDirection.In), {BackgroundTransparency = 0}):Play()
				end
				TweenService:Create(winScale, TweenInfo.new(0.2, Enum.EasingStyle.Quint, Enum.EasingDirection.In), {Scale = veil and 0.82 or 0.88}):Play()
				task.delay(0.21, function()
					if closing == mine then
						frame.Visible = false; winScale.Scale = 1
						if veil then veil.BackgroundTransparency = 1 end
					end
				end)
			end
			w.wantOpen = on
			updateArrow()
			w.OnClose.Fire(on)

			if on and cfg.startCollapsed and not w.collapsedInit then
				w.collapsedInit = true
				setMinimized(true)
			end
		end
		function w.IsOpen() return frame.Visible and w.wantOpen ~= false end
		local function suckClose()
			if w.closingNow then return end
			w.closingNow = true
			local function finish()
				if w.finished then return end
				w.finished = true
				pcall(function() if lib.OnUnload then lib.OnUnload() end end)
				pcall(function()
					local genv = typeof(getgenv) == "function" and getgenv() or _G
					if type(genv.SourcesHubSaeCleanup) == "function" then genv.SourcesHubSaeCleanup() end
				end)
				pcall(function() gui:Destroy() end)
			end
			task.delay(1.8, finish)
			if lib.NoAnim then finish(); return end
			task.spawn(function()
				local ok = pcall(function()
					ov.Visible = false
					local block = Instance.new("TextButton", frame)
					block.Size = UDim2.new(1, 0, 1, 0); block.BackgroundTransparency = 1; block.Text = ""; block.ZIndex = 950
					local sx, sy = frame.Size.X.Offset, frame.Size.Y.Offset
					local p0 = frame.Position
					local ax, ay = p0.X.Offset + sx / 2, p0.Y.Offset + sy / 2
					frame.AnchorPoint = Vector2.new(0.5, 0.5)
					frame.Position = UDim2.new(p0.X.Scale, ax, p0.Y.Scale, ay)
					local tx, ty = 0.5, 26
					local elapsed = 0
					local dur = 0.75
					while true do
						local t = math.min(elapsed / dur, 1)
						local e = t * t * t
						local k = t * t * (3 - 2 * t)
						winScale.Scale = 1 - 0.97 * e
						frame.Position = UDim2.new(p0.X.Scale + (tx - p0.X.Scale) * k, ax * (1 - k), p0.Y.Scale + (0 - p0.Y.Scale) * k, ay + (ty - ay) * k)
						if veil then veil.BackgroundTransparency = 1 - math.min(t * 1.6, 1) end
						if t >= 1 then break end
						elapsed = elapsed + math.min(tonumber(task.wait()) or 0.016, 0.1)
					end
				end)
				finish()
			end)
		end
		close.MouseButton1Click:Connect(function()
			if cfg.isMain then
				suckClose()
			else
				setMinimized(true)
			end
		end)
		w.Close = suckClose
		drag(header, frame)

		-- tabs
		function w.ApplyFilter(q)
			q = string.lower(tostring(q or ""))
			w.query = q
			local tab = w.tabs[w.current or ""]
			if not tab then return end
			local anyShown = false
			for _, sl in ipairs(tab.slots or {}) do
				if not sl.sub and sl.holder.Parent then
					local nm = sl.holder:GetAttribute("sname") or ""
					local show = q == "" or string.find(nm, q, 1, true) ~= nil
					sl.holder.Visible = show
					if show then anyShown = true end
					if sl.info then
						if not show then
							for _, hh in ipairs(sl.info.subs) do hh.Visible = false end
						elseif sl.info.refresh then
							sl.info.refresh()
						end
					end
				end
			end
			for _, sc in ipairs(tab.secs or {}) do
				if q == "" then
					sc.head.Visible = true; sc.body.Visible = sc.IsOpen()
				else
					local any = false
					for _, sl in ipairs(tab.slots or {}) do
						if not sl.sub and sl.holder.Parent == sc.body and sl.holder.Visible then any = true; break end
					end
					sc.head.Visible = any; sc.body.Visible = any
				end
			end
			if w.noResults then w.noResults.Visible = q ~= "" and not anyShown end
		end
		function w.AddTab(name, hidden, display)
			local tab = {name = name, sections = {}, window = w}
			local page = Instance.new("ScrollingFrame", content)
			page.Name = name; page.Size = UDim2.new(1, 0, 1, 0)
			page.BackgroundTransparency = 1; page.BorderSizePixel = 0; page.ScrollBarThickness = 3
			page.ScrollBarImageColor3 = C.ACCENT; page.CanvasSize = UDim2.new(0, 0, 0, 0)
			page.AutomaticCanvasSize = Enum.AutomaticSize.Y; page.Visible = false
			local pl = Instance.new("UIListLayout", page)
			pl.Padding = UDim.new(0, 5); pl.SortOrder = Enum.SortOrder.LayoutOrder
			local pp = Instance.new("UIPadding", page)
			pp.PaddingTop = UDim.new(0, 4); pp.PaddingLeft = UDim.new(0, 6); pp.PaddingRight = UDim.new(0, 6)
			pp.PaddingBottom = UDim.new(0, 10)
			tab.page = page
			if tabBar and not hidden then
				local btn = Instance.new("TextButton", tabBar)
				btn.Size = UDim2.new(1, 0, 0, 30)
				btn.BackgroundColor3 = C.ROW; btn.BackgroundTransparency = 1
				btn.Text = ""; btn.AutoButtonColor = false; btn.BorderSizePixel = 0; btn.LayoutOrder = TAB_ORDER[name] or (10 + #w.order)
				local bl = label(btn, display or name, UDim2.new(1, -14, 1, 0), C.WHITE, Enum.Font.GothamBold)
				bl.Position = UDim2.new(0, 12, 0, 0); bl.TextSize = 12; bl.TextTruncate = Enum.TextTruncate.AtEnd
				bl.TextTransparency = 0.3
				corner(btn, 10)
				local btnStroke = addLivingStroke(btn, 1.2, true, true)
				btnStroke.Transparency = 0.6
				local bar = Instance.new("Frame", btn)
				bar.Size = UDim2.new(0, 3, 0, 16); bar.Position = UDim2.new(0, 0, 0.5, -8)
				bar.BackgroundColor3 = C.MOON2; bar.BorderSizePixel = 0; bar.BackgroundTransparency = 1
				corner(bar, 2)
				pressFx(btn)
				tab.btn = btn; tab.btnLabel = bl; tab.bar = bar; tab.btnStroke = btnStroke
				btn.MouseEnter:Connect(function() if not tab.isOn then TweenService:Create(btn, TweenInfo.new(0.1), {BackgroundTransparency = 0.7}):Play() end end)
				btn.MouseLeave:Connect(function() if not tab.isOn then TweenService:Create(btn, TweenInfo.new(0.15), {BackgroundTransparency = 1}):Play() end end)
				btn.MouseButton1Click:Connect(function() w.Select(name) end)
			end
			if hidden then page.Parent = nil end
			w.tabs[name] = tab
			table.insert(w.order, name)
			return tab
		end
		function w.Select(name)
			local target = w.tabs[name]
			if not target then return end
			local firstSelect = w.current == nil
			w.current = name
			if w.ApplyFilter and w.query and w.query ~= "" then task.defer(function() w.ApplyFilter(w.query) end) end
			for n, t in pairs(w.tabs) do
				local on = n == name
				if t.holder and t.holder.Parent then t.holder.Visible = on end
				t.isOn = on
				if on and not t.page.Visible and not firstSelect then
					t.basePos = t.basePos or t.page.Position
					t.page.Position = t.basePos + UDim2.fromOffset(44, 0)
					t.page.Visible = true
					TweenService:Create(t.page, TweenInfo.new(0.34, Enum.EasingStyle.Quint, Enum.EasingDirection.Out), {Position = t.basePos}):Play()
				else
					t.page.Visible = on
					if not on and t.basePos then t.page.Position = t.basePos end
				end
				if t.btn then
					TweenService:Create(t.btn, TweenInfo.new(0.15), {
						BackgroundColor3 = on and C.ON_BG or C.ROW,
						BackgroundTransparency = on and 0.2 or 1}):Play()
					TweenService:Create(t.btnLabel, TweenInfo.new(0.15), {TextTransparency = on and 0 or 0.3}):Play()
					if t.btnStroke then TweenService:Create(t.btnStroke, TweenInfo.new(0.15), {Transparency = on and 0 or 0.6}):Play() end
					TweenService:Create(t.bar, TweenInfo.new(0.18), {BackgroundTransparency = on and 0 or 1}):Play()
				end
			end
			if not firstSelect and w.Transition then w.Transition() end
		end
		w.header = header; w.title = title; w.moon = moon
		table.insert(windows, w)
		return w
	end

	-- ---------- controls ----------
	local fireAtFinalize = {}          -- controls whose callback runs once the UI is complete
	local groups = {}
	local function pathKey(section, name) return section.tab.name .. ">" .. section.name .. ">" .. tostring(name) end

	local Section = {}
	Section.__index = Section

	-- one row in the section body; SubOf rows sit indented under their parent
	function Section:_slot(height, subOf)
		local order
		if subOf and subOf._slotInfo then
			subOf._slotInfo.children = subOf._slotInfo.children + 1
			order = subOf._slotInfo.order + subOf._slotInfo.children
		else
			self.count = self.count + 1
			order = self.count * 1000
		end
		local holder = Instance.new("Frame", self.body)
		holder.Size = UDim2.new(1, 0, 0, height)
		holder.BackgroundTransparency = 1
		holder.LayoutOrder = order
		local indent = subOf and 14 or 0
		local row = Instance.new("Frame", holder)
		row.Size = UDim2.new(1, -indent - 6, 1, 0); row.Position = UDim2.new(0, indent, 0, 0)
		row.BackgroundColor3 = C.ROW; row.BackgroundTransparency = 0.35; row.BorderSizePixel = 0
		corner(row, 10); addLivingStroke(row, 1)
		local info = {order = order, children = 0, holder = holder, subs = {}, open = false}
		self.tab.slots = self.tab.slots or {}
		table.insert(self.tab.slots, {holder = holder, info = info, sub = subOf ~= nil})
		do
			row.BackgroundTransparency = 0.15
			row.MouseEnter:Connect(function() TweenService:Create(row, TweenInfo.new(0.12), {BackgroundTransparency = 0.04}):Play() end)
			row.MouseLeave:Connect(function() TweenService:Create(row, TweenInfo.new(0.18), {BackgroundTransparency = 0.15}):Play() end)
			local edge = Instance.new("Frame", row)
			edge.Name = "Edge"; edge.Size = UDim2.new(0, 3, 1, -12); edge.Position = UDim2.new(0, 0, 0, 6)
			edge.BackgroundColor3 = C.MOON2; edge.BackgroundTransparency = 1; edge.BorderSizePixel = 0
			corner(edge, 2)
			info.edge = edge
		end
		if subOf and subOf._slotInfo then
			table.insert(subOf._slotInfo.subs, holder)
			subOf._refreshSubs()
		end
		return holder, row, info
	end

	local function nameLabel(row, text, width)
		local l = label(row, tostring(text), UDim2.new(1, width or -62, 0, 18), C.WHITE, Enum.Font.GothamBold)
		l.Position = UDim2.new(0, 10, 0, 5); l.TextSize = 11.5; l.TextTruncate = Enum.TextTruncate.AtEnd
		liveGrad(l)
		if row.Parent then row.Parent:SetAttribute("sname", string.lower(tostring(text))) end
		return l
	end
	local function noteLabel(row, text)
		if not text or text == "" then return end
		local n = label(row, tostring(text), UDim2.new(1, -18, 0, 12), C.DIM, Enum.Font.GothamMedium)
		n.Position = UDim2.new(0, 10, 0, 22); n.TextSize = 8.5; n.TextTruncate = Enum.TextTruncate.AtEnd
	end
	-- parent handles show / hide their SubOf rows (visible while ON or opened by hand)
	local function makeParentLogic(handle, info, getOn)
		local btn
		handle._slotInfo = info
		handle._refreshSubs = function()
			local show = info.open or getOn()
			for _, h in ipairs(info.subs) do h.Visible = show end
			if btn then btn.Visible = #info.subs > 0; btn.Text = ">"; btn.Rotation = show and 90 or 0 end
		end
		handle._setArrow = function(b) btn = b; handle._refreshSubs() end
		info.refresh = handle._refreshSubs
	end
	local function arrowButton(row, handle, info, x)
		local b = Instance.new("TextButton", row)
		b.Size = UDim2.new(0, 18, 0, 18); b.Position = UDim2.new(1, x, 0, 5)
		b.BackgroundTransparency = 1; b.Text = ">"; b.TextSize = 12; b.TextColor3 = C.DIM
		b.Font = Enum.Font.GothamBold; b.Visible = false
		pressFx(b)
		b.MouseButton1Click:Connect(function() info.open = not info.open; handle._refreshSubs() end)
		handle._setArrow(b)
	end

	local function register(section, cfg, handle, kind)
		handle.Name = cfg.Name
		handle.Kind = kind
		lib.handles[pathKey(section, cfg.Name)] = handle
	end

	function Section:CreateToggle(cfg)
		local key = pathKey(self, cfg.Name)
		local value = cfg.Default == true
		local restored = false
		if store[key] ~= nil then value = store[key] == true; restored = value ~= (cfg.Default == true) end
		local h = {}
		local hasNote = cfg.Note and cfg.Note ~= ""
		local holder, row, info = self:_slot(hasNote and 38 or 28, cfg.SubOf)
		local mainStyle = info.edge ~= nil
		nameLabel(row, cfg.Name, mainStyle and -92 or -84)
		noteLabel(row, cfg.Note)
		local pill, btn, setSwitch
		local function paintRow(on)
			if not mainStyle then return end
			TweenService:Create(row, TweenInfo.new(0.18), {BackgroundColor3 = on and C.ON_BG or C.ROW}):Play()
			TweenService:Create(info.edge, TweenInfo.new(0.18), {BackgroundTransparency = on and 0 or 1}):Play()
		end
		if mainStyle then
			pill, btn, setSwitch = makeCheck(row, value)
			pill.Position = UDim2.new(1, -34, 0.5, -13)
			if value then row.BackgroundColor3 = C.ON_BG; info.edge.BackgroundTransparency = 0 end
		else
			pill, btn, setSwitch = makeSwitch(row, value)
			pill.Position = UDim2.new(1, -52, 0, 4)
		end
		h.Instance = holder
		h._controller = {GetValue = function() return value end}
		local subs = newSignalList()
		local groupRef
		makeParentLogic(h, info, function() return value end)
		arrowButton(row, h, info, mainStyle and -58 or -74)
		function h.Get() return value end
		function h.GetValue() return value end
		function h.Subscribe(_, fn) return subs.Connect(fn) end
		local set
		set = function(_, v, fire)
			v = v == true
			if v == value then return end
			value = v
			setSwitch(v); paintRow(v)
			setStored(key, v)
			h._refreshSubs()
			if v and groupRef then
				local on = {}
				for _, m in ipairs(groupRef.members) do if m ~= h and m.Get() then on[#on + 1] = m end end
				local extra = #on + 1 - (groupRef.max or 1)
				for i = 1, extra do if on[i] then on[i]:Set(false, true) end end
			end
			if fire ~= false and cfg.Callback then task.spawn(cfg.Callback, v) end
			subs.Fire(v)
		end
		h.Set = set
		function h.JoinExclusiveGroup(_, g)
			groupRef = g
			table.insert(g.members, h)
		end
		btn.MouseButton1Click:Connect(function() set(h, not value, true) end)
		register(self, cfg, h, "Toggle")
		if cfg.Callback and (value or restored) then table.insert(fireAtFinalize, function() cfg.Callback(value) end) end
		return h
	end

	function Section:CreateButton(cfg)
		local hasNote = cfg.Note and cfg.Note ~= ""
		local holder, row = self:_slot(hasNote and 38 or 28, cfg.SubOf)
		local bw = cfg.ButtonWidth or 64
		nameLabel(row, cfg.Name, -(bw + 20))
		noteLabel(row, cfg.Note)
		local b = Instance.new("TextButton", row)
		b.Size = UDim2.new(0, bw, 0, 22); b.Position = UDim2.new(1, -(bw + 8), 0.5, -11)
		b.BackgroundColor3 = C.MOON; b.BackgroundTransparency = 0; b.AutoButtonColor = false
		b.Text = ""; b.BorderSizePixel = 0
		corner(b, 7)
		local bg = Instance.new("UIGradient", b)
		bg.Rotation = 90
		bg.Color = ColorSequence.new({ColorSequenceKeypoint.new(0, C.MOON2), ColorSequenceKeypoint.new(1, C.MOON)})
		local bl = label(b, cfg.ButtonText or "Run", UDim2.new(1, 0, 1, 0), C.WHITE, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
		bl.TextSize = 10; bl.ZIndex = 2
		local pulse = pressFx(b)
		local h = {Instance = holder}
		function h.SetText(t) bl.Text = tostring(t) end
		function h.Pulse() pulse() end
		local busy = false
		b.MouseButton1Click:Connect(function()
			pulse()
			bg.Offset = Vector2.new(0, -1)
			TweenService:Create(bg, TweenInfo.new(0.35, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {Offset = Vector2.new(0, 0)}):Play()
			if cfg.Callback then task.spawn(cfg.Callback) end
			if cfg.ConfirmText and not busy then
				busy = true
				local old = bl.Text
				bl.Text = cfg.ConfirmText
				b.BackgroundColor3 = Color3.fromRGB(34, 140, 90)
				task.delay(1.4, function() bl.Text = old; b.BackgroundColor3 = C.MOON; busy = false end)
			end
		end)
		register(self, cfg, h, "Button")
		return h
	end

	function Section:_createButtonOld(cfg)
		local hasNote = cfg.Note and cfg.Note ~= ""
		local holder, row = self:_slot(hasNote and 38 or 28, cfg.SubOf)
		local bw = cfg.ButtonWidth or 64
		nameLabel(row, cfg.Name, -(bw + 20))
		noteLabel(row, cfg.Note)
		local b = Instance.new("TextButton", row)
		b.Size = UDim2.new(0, bw, 0, 20); b.Position = UDim2.new(1, -(bw + 8), 0, hasNote and 9 or 4)
		b.BackgroundColor3 = C.ROW; b.BackgroundTransparency = 0.35; b.AutoButtonColor = false
		b.Text = ""; b.BorderSizePixel = 0
		corner(b, 8); addLivingStroke(b, 1)
		local bl = label(b, cfg.ButtonText or "Run", UDim2.new(1, 0, 1, 0), C.WHITE, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
		bl.TextSize = 9.5; bl.ZIndex = 2
		liveGrad(bl)
		local pulse = pressFx(b)
		local h = {Instance = holder}
		function h.SetText(t) bl.Text = tostring(t) end
		function h.Pulse() pulse() end
		local busy = false
		b.MouseButton1Click:Connect(function()
			pulse()
			if cfg.Callback then task.spawn(cfg.Callback) end
			if cfg.ConfirmText and not busy then
				busy = true
				local old = bl.Text
				bl.Text = cfg.ConfirmText
				b.BackgroundColor3 = Color3.fromRGB(20, 80, 50)
				task.delay(1.4, function() bl.Text = old; b.BackgroundColor3 = C.ROW; busy = false end)
			end
		end)
		register(self, cfg, h, "Button")
		return h
	end

	function Section:CreateText(cfg)
		local holder = Instance.new("Frame", self.body)
		self.count = self.count + 1
		holder.LayoutOrder = self.count * 1000
		holder.Size = UDim2.new(1, 0, 0, 0); holder.AutomaticSize = Enum.AutomaticSize.Y
		holder.BackgroundTransparency = 1
		local info
		if cfg.SubOf and cfg.SubOf._slotInfo then
			cfg.SubOf._slotInfo.children = cfg.SubOf._slotInfo.children + 1
			holder.LayoutOrder = cfg.SubOf._slotInfo.order + cfg.SubOf._slotInfo.children
			table.insert(cfg.SubOf._slotInfo.subs, holder); cfg.SubOf._refreshSubs()
		end
		local row = Instance.new("Frame", holder)
		row.Size = UDim2.new(1, -6, 0, 0); row.AutomaticSize = Enum.AutomaticSize.Y
		row.BackgroundColor3 = C.ROW; row.BackgroundTransparency = 0.25; row.BorderSizePixel = 0
		corner(row, 10); addLivingStroke(row, 1)
		local rl = Instance.new("UIListLayout", row)
		rl.SortOrder = Enum.SortOrder.LayoutOrder; rl.Padding = UDim.new(0, 1)
		local rp = Instance.new("UIPadding", row)
		rp.PaddingLeft = UDim.new(0, 10); rp.PaddingRight = UDim.new(0, 10); rp.PaddingTop = UDim.new(0, 5); rp.PaddingBottom = UDim.new(0, 6)
		local nm = label(row, string.upper(tostring(cfg.Name or "")), UDim2.new(1, 0, 0, 11), C.MOON2, Enum.Font.GothamBold)
		nm.TextSize = 8.5; nm.LayoutOrder = 1
		local tx = label(row, tostring(cfg.Text or ""), UDim2.new(1, 0, 0, 0), C.SILVER, Enum.Font.GothamMedium)
		tx.TextSize = 10; tx.TextWrapped = true; tx.AutomaticSize = Enum.AutomaticSize.Y
		tx.TextYAlignment = Enum.TextYAlignment.Top; tx.LayoutOrder = 2
		holder:SetAttribute("sname", string.lower(tostring(cfg.Name or "") .. " " .. tostring(cfg.Text or "")))
		self.tab.slots = self.tab.slots or {}
		table.insert(self.tab.slots, {holder = holder, sub = cfg.SubOf ~= nil})
		local h = {Instance = holder}
		local text = tostring(cfg.Text or "")
		function h.Set(_, t) text = tostring(t); tx.Text = text end
		function h.Get() return text end
		register(self, cfg, h, "Text")
		return h
	end

	function Section:CreateLabel(cfg)
		return self:CreateText({Name = cfg.Name, Text = cfg.Text, SubOf = cfg.SubOf})
	end

	function Section:CreateSlider(cfg)
		local key = pathKey(self, cfg.Name)
		local minV, maxV = tonumber(cfg.Min) or 0, tonumber(cfg.Max) or 100
		local inc = tonumber(cfg.Increment) or 1
		local value = tonumber(cfg.Default) or minV
		local restored = false
		if type(store[key]) == "number" then value = store[key]; restored = value ~= (tonumber(cfg.Default) or minV) end
		local holder, row = self:_slot(40, cfg.SubOf)
		nameLabel(row, cfg.Name, -96)
		local valBox = Instance.new("TextBox", row)
		valBox.Size = UDim2.new(0, 84, 0, 18); valBox.Position = UDim2.new(1, -92, 0, 4)
		valBox.BackgroundTransparency = 1; valBox.TextColor3 = C.ACCENT2; valBox.Font = Enum.Font.GothamBold
		valBox.TextSize = 10.5; valBox.TextXAlignment = Enum.TextXAlignment.Right; valBox.ClearTextOnFocus = false
		valBox.Text = ""
		local track = Instance.new("Frame", row)
		track.Size = UDim2.new(1, -20, 0, 6); track.Position = UDim2.new(0, 10, 1, -12)
		track.BackgroundColor3 = C.TRACKOFF; track.BorderSizePixel = 0; corner(track, 3)
		local fill = Instance.new("Frame", track)
		fill.Size = UDim2.new(0, 0, 1, 0); fill.BackgroundColor3 = C.ACCENT; fill.BorderSizePixel = 0; corner(fill, 3)
		local fg = Instance.new("UIGradient", fill)
		fg.Color = ColorSequence.new({ColorSequenceKeypoint.new(0, C.DEEP2), ColorSequenceKeypoint.new(1, C.ACCENT2)})
		local thumb = Instance.new("Frame", track)
		thumb.Size = UDim2.new(0, 14, 0, 14); thumb.AnchorPoint = Vector2.new(0.5, 0.5)
		thumb.BackgroundColor3 = C.WHITE; thumb.BorderSizePixel = 0; corner(thumb, 7); stroke(thumb, C.ACCENT, 2)
		local h = {Instance = holder}
		local function fmt(v)
			if cfg.ValueFormat then
				local ok, s = pcall(cfg.ValueFormat, v)
				if ok and s then return tostring(s) end
			end
			local s
			if cfg.AllowDecimals or inc % 1 ~= 0 then s = string.format("%g", math.floor(v * 100 + 0.5) / 100) else s = tostring(math.floor(v + 0.5)) end
			if cfg.Unit and cfg.Unit ~= "" then s = s .. " " .. cfg.Unit end
			return s
		end
		local function snap(v)
			v = math.clamp(v, minV, maxV)
			if not cfg.AllowDecimals and inc > 0 then v = minV + math.floor((v - minV) / inc + 0.5) * inc end
			return math.clamp(v, minV, maxV)
		end
		local function paint()
			local t = maxV > minV and (value - minV) / (maxV - minV) or 0
			fill.Size = UDim2.new(t, 0, 1, 0); thumb.Position = UDim2.new(t, 0, 0.5, 0)
			if not valBox:IsFocused() then valBox.Text = fmt(value) end
		end
		local subs = newSignalList()
		local function set(_, v, fire)
			v = snap(tonumber(v) or value)
			if v == value then paint(); return end
			value = v; paint(); setStored(key, v)
			if fire ~= false and cfg.Callback then task.spawn(cfg.Callback, v) end
			subs.Fire(v)
		end
		h.Set = set
		function h.Get() return value end
		function h.GetValue() return value end
		function h.Subscribe(_, fn) return subs.Connect(fn) end
		value = snap(value); paint()
		local dragging = false
		track.InputBegan:Connect(function(inp)
			if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then dragging = true end
		end)
		UIS.InputEnded:Connect(function(inp)
			if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then dragging = false end
		end)
		UIS.InputChanged:Connect(function(inp)
			if not dragging then return end
			if inp.UserInputType ~= Enum.UserInputType.MouseMovement and inp.UserInputType ~= Enum.UserInputType.Touch then return end
			local a, s = track.AbsolutePosition, track.AbsoluteSize
			local rel = math.clamp((inp.Position.X - a.X) / math.max(s.X, 1), 0, 1)
			set(h, minV + (maxV - minV) * rel, true)
		end)
		valBox.FocusLost:Connect(function()
			local n
			if cfg.ValueParse then local ok, r = pcall(cfg.ValueParse, valBox.Text); if ok then n = r end end
			n = n or tonumber(string.match(valBox.Text, "-?%d+%.?%d*"))
			if n then set(h, n, true) else paint() end
		end)
		register(self, cfg, h, "Slider")
		if cfg.Callback then table.insert(fireAtFinalize, function() cfg.Callback(value) end) end
		return h
	end

	function Section:CreateDropdown(cfg)
		local key = pathKey(self, cfg.Name)
		local options = cfg.Options or {}
		local value = cfg.Default
		if type(store[key]) == "string" and table.find(options, store[key]) then value = store[key] end
		if value == nil then value = options[1] end
		local hasNote = cfg.Note and cfg.Note ~= ""
		local holder, row = self:_slot(hasNote and 38 or 28, cfg.SubOf)
		nameLabel(row, cfg.Name, -130)
		noteLabel(row, cfg.Note)
		local box = Instance.new("TextButton", row)
		box.Size = UDim2.new(0, 116, 0, 20); box.Position = UDim2.new(1, -124, 0, 4)
		box.BackgroundColor3 = Color3.fromRGB(12, 18, 32); box.TextColor3 = C.WHITE; styleText(box)
		box.Text = tostring(value); box.TextSize = 9.5; box.Font = Enum.Font.GothamBold; box.BorderSizePixel = 0
		box.TextTruncate = Enum.TextTruncate.AtEnd
		corner(box, 6); addLivingStroke(box, 1)
		box.TextXAlignment = Enum.TextXAlignment.Left
		local bpad = Instance.new("UIPadding", box); bpad.PaddingLeft = UDim.new(0, 8); bpad.PaddingRight = UDim.new(0, 18)
		local chev = label(box, ">", UDim2.new(0, 14, 1, 0), C.MOON2, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
		chev.Position = UDim2.new(1, -16, 0, 0); chev.TextSize = 10; chev.Rotation = 90
		local h = {Instance = holder}
		local subs = newSignalList()
		local function set(_, v, fire)
			if v == nil or v == value then return end
			value = v; box.Text = tostring(v); setStored(key, v)
			if fire ~= false and cfg.Callback then task.spawn(cfg.Callback, v) end
			subs.Fire(v)
		end
		h.Set = set
		function h.Get() return value end
		function h.GetValue() return value end
		function h.Subscribe(_, fn) return subs.Connect(fn) end
		function h.SetOptions(_, opts, default, fire)
			options = opts or {}
			local nv = default
			if nv == nil or not table.find(options, nv) then nv = table.find(options, value) and value or options[1] end
			value = nil
			set(h, nv, fire == true)
			if value == nil then value = nv; box.Text = tostring(nv) end
		end
		box.MouseButton1Click:Connect(function()
			self.window.Pick({title = tostring(cfg.Name), options = options, multi = false,
				isOn = function(o) return o == value end,
				toggle = function(o) set(h, o, true) end})
		end)
		register(self, cfg, h, "Dropdown")
		if cfg.Callback then table.insert(fireAtFinalize, function() cfg.Callback(value) end) end
		return h
	end

	function Section:CreateMultiDropdown(cfg)
		local key = pathKey(self, cfg.Name)
		local options = cfg.Options or {}
		local selected = {}
		if type(cfg.Default) == "table" then
			for k, v in pairs(cfg.Default) do
				if v == true and type(k) == "string" then selected[k] = true elseif type(v) == "string" then selected[v] = true end
			end
		end
		local restored = false
		if type(store[key]) == "table" then
			selected = {}
			for k, v in pairs(store[key]) do if v == true then selected[k] = true end end
			restored = next(selected) ~= nil
		end
		local hasNote = cfg.Note and cfg.Note ~= ""
		local holder, row = self:_slot(hasNote and 38 or 28, cfg.SubOf)
		nameLabel(row, cfg.Name, -100)
		noteLabel(row, cfg.Note)
		local box = Instance.new("TextButton", row)
		box.Size = UDim2.new(0, 86, 0, 20); box.Position = UDim2.new(1, -94, 0, 4)
		box.BackgroundColor3 = Color3.fromRGB(12, 18, 32); box.TextColor3 = C.WHITE; styleText(box)
		box.TextSize = 9.5; box.Font = Enum.Font.GothamBold; box.BorderSizePixel = 0; box.Name = "Value"
		corner(box, 6); addLivingStroke(box, 1)
		box.TextXAlignment = Enum.TextXAlignment.Left
		local bpad = Instance.new("UIPadding", box); bpad.PaddingLeft = UDim.new(0, 8); bpad.PaddingRight = UDim.new(0, 18)
		local chev = label(box, ">", UDim2.new(0, 14, 1, 0), C.MOON2, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
		chev.Position = UDim2.new(1, -16, 0, 0); chev.TextSize = 10; chev.Rotation = 90
		local h = {Instance = holder}
		local subs = newSignalList()
		local function count() local n = 0; for _ in pairs(selected) do n = n + 1 end; return n end
		local function paint()
			local n = count()
			if n == 0 then box.Text = "All"
			elseif n == 1 then box.Text = tostring(next(selected))
			else box.Text = n .. " picked" end
		end
		local function copy() local c = {}; for k in pairs(selected) do c[k] = true end; return c end
		local function changed(fire)
			paint(); setStored(key, copy())
			if fire ~= false and cfg.Callback then task.spawn(cfg.Callback, copy()) end
			subs.Fire(copy())
		end
		paint()
		function h.Get() return copy() end
		function h.GetValue() return copy() end
		function h.Subscribe(_, fn) return subs.Connect(fn) end
		function h.Set(_, v, fire)
			selected = {}
			if type(v) == "table" then
				for k, x in pairs(v) do
					if x == true and type(k) == "string" then selected[k] = true elseif type(x) == "string" then selected[x] = true end
				end
			end
			changed(fire)
		end
		function h.SetOptions(_, opts) options = opts or {} end
		box.MouseButton1Click:Connect(function()
			self.window.Pick({title = tostring(cfg.Name), options = options, multi = true,
				isOn = function(o) return selected[o] == true end,
				toggle = function(o) if selected[o] then selected[o] = nil else selected[o] = true end; changed(true) end,
				onClear = function() selected = {}; changed(true) end})
		end)
		register(self, cfg, h, "MultiDropdown")
		if cfg.Callback and (restored or count() > 0) then table.insert(fireAtFinalize, function() cfg.Callback(copy()) end) end
		return h
	end

	function Section:CreateInput(cfg)
		local key = pathKey(self, cfg.Name)
		local value = cfg.Default and tostring(cfg.Default) or ""
		if type(store[key]) == "string" then value = store[key] end
		local holder, row = self:_slot(28, cfg.SubOf)
		nameLabel(row, cfg.Name, -130)
		local tb = Instance.new("TextBox", row)
		tb.Size = UDim2.new(0, 116, 0, 20); tb.Position = UDim2.new(1, -124, 0, 4)
		tb.BackgroundColor3 = Color3.fromRGB(12, 18, 32); tb.TextColor3 = C.WHITE; styleText(tb)
		tb.PlaceholderText = cfg.Placeholder or ""; tb.PlaceholderColor3 = C.DIM
		tb.Text = value; tb.TextSize = 9.5; tb.Font = Enum.Font.GothamMedium; tb.BorderSizePixel = 0
		tb.ClearTextOnFocus = false
		corner(tb, 6); addLivingStroke(tb, 1)
		local h = {Instance = holder}
		function h.Get() return value end
		function h.GetValue() return value end
		function h.Set(_, v, fire)
			value = tostring(v or ""); tb.Text = value; setStored(key, value)
			if fire ~= false and cfg.Callback then task.spawn(cfg.Callback, value) end
		end
		tb.FocusLost:Connect(function()
			local t = tb.Text
			if cfg.MaxLength then t = string.sub(t, 1, cfg.MaxLength) end
			h.Set(h, t, true)
		end)
		register(self, cfg, h, "Input")
		return h
	end

	-- ---------- sections / tabs ----------
	local EVENT_SECTIONS = {["Dr Scramble Lab & Mech"] = true}
	local HIDDEN_TABS = {Predictor = true, Discord = true}

	local Tab = {}
	Tab.__index = Tab
	function Tab:CreateSection(cfg)
		local target = self
		local win = self.window
		if EVENT_SECTIONS[cfg.Name] and lib.eventsWindow then
			target = lib.eventsWindow.tabs.Events
			win = lib.eventsWindow
		end
		local sec = setmetatable({name = cfg.Name, tab = target, window = win, count = 0}, Section)
		local page = target.page
		target.secCount = (target.secCount or 0) + 1
		local head = Instance.new("TextButton", page)
		head.Size = UDim2.new(1, 0, 0, 28); head.BackgroundTransparency = 1; head.Text = ""
		head.LayoutOrder = target.secCount * 10
		local accent = Instance.new("Frame", head)
		accent.Size = UDim2.new(0, 3, 0, 14); accent.Position = UDim2.new(0, 2, 0.5, -7)
		accent.BackgroundColor3 = C.MOON; accent.BorderSizePixel = 0; corner(accent, 2)
		local lbl = label(head, tostring(cfg.Name), UDim2.new(1, -30, 1, 0), C.WHITE, Enum.Font.GothamBold)
		lbl.TextSize = 12.5; lbl.Position = UDim2.new(0, 12, 0, 0)
		local arrow = label(head, ">", UDim2.new(0, 16, 1, 0), C.DIM, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
		arrow.Position = UDim2.new(1, -18, 0, 0); arrow.TextSize = 10
		local body = Instance.new("Frame", page)
		body.Size = UDim2.new(1, 0, 0, 0); body.AutomaticSize = Enum.AutomaticSize.Y
		body.BackgroundTransparency = 1; body.LayoutOrder = target.secCount * 10 + 1
		local bl = Instance.new("UIListLayout", body)
		bl.Padding = UDim.new(0, 4); bl.SortOrder = Enum.SortOrder.LayoutOrder
		sec.body = body
		local open = cfg.Expanded ~= false
		body.Visible = open; arrow.Rotation = open and 90 or 0
		arrow.TextColor3 = C.MOON2
		local hline = Instance.new("Frame", head)
		hline.Size = UDim2.new(1, -4, 0, 1); hline.Position = UDim2.new(0, 2, 1, -1)
		hline.BackgroundColor3 = C.BORDER; hline.BackgroundTransparency = 0.35; hline.BorderSizePixel = 0
		target.secs = target.secs or {}
		table.insert(target.secs, {head = head, body = body, IsOpen = function() return open end})
		head.MouseButton1Click:Connect(function()
			open = not open; body.Visible = open
			TweenService:Create(arrow, TweenInfo.new(0.16), {Rotation = open and 90 or 0}):Play()
		end)
		return sec
	end
	for _, name in ipairs({"CreateToggle", "CreateButton", "CreateText", "CreateLabel", "CreateSlider", "CreateDropdown", "CreateMultiDropdown", "CreateInput"}) do
		Tab[name] = function(self, cfg)
			self._default = self._default or self:CreateSection({Name = "General", Expanded = true})
			return self._default[name](self._default, cfg)
		end
	end

	-- ---------- extra tool windows (same look/API as the Events window) ----------
	lib.NewToolWindow = function(cfg)
		local main = lib.mainWindow
		local key = cfg.tabName or "Tool"
		local raw = main.tabs[key]
		if not raw then raw = main.AddTab(key, false, cfg.tabTitle or cfg.title) end
		-- a fresh holder and page every time: the logic may tear the panel down and rebuild it
		if raw.holder and raw.holder.Parent then raw.holder:Destroy() end
		if raw.page and raw.page.Parent then raw.page:Destroy() end
		local holder = Instance.new("Frame", main.content)
		holder.Name = "Embed_" .. key
		holder.Size = UDim2.new(1, 0, 1, 0); holder.BackgroundTransparency = 1; holder.ClipsDescendants = true
		holder.Visible = main.current == key
		local page = Instance.new("ScrollingFrame", holder)
		page.Name = key; page.Size = UDim2.new(1, 0, 1, 0)
		page.BackgroundTransparency = 1; page.BorderSizePixel = 0; page.ScrollBarThickness = 3
		page.ScrollBarImageColor3 = C.ACCENT; page.CanvasSize = UDim2.new(0, 0, 0, 0)
		page.AutomaticCanvasSize = Enum.AutomaticSize.Y; page.Visible = main.current == key
		local pl = Instance.new("UIListLayout", page)
		pl.Padding = UDim.new(0, 5); pl.SortOrder = Enum.SortOrder.LayoutOrder
		local pp = Instance.new("UIPadding", page)
		pp.PaddingTop = UDim.new(0, 4); pp.PaddingLeft = UDim.new(0, 6); pp.PaddingRight = UDim.new(0, 6)
		pp.PaddingBottom = UDim.new(0, 10)
		raw.page = page; raw.holder = holder; raw.basePos = nil
		local tab = setmetatable(raw, Tab)
		tab.window = main
		local win = {tab = tab, content = holder, frame = holder, name = cfg.name, title = Instance.new("TextLabel")}
		win.OnClose = newSignalList()
		win.wantOpen = false
		function win.SetOpen(on) win.wantOpen = on == true; win.OnClose.Fire(on == true) end
		function win.IsOpen() return win.wantOpen end
		function win.Select() main.Select(key) end
		return win
	end

	-- ---------- window API ----------
	local Win = {}
	Win.__index = Win
	function Win:GetDefaultTab() return self.defaultTab end
	function Win:CreateTab(cfg)
		local hidden = HIDDEN_TABS[cfg.Name] == true
		local t = self.main.AddTab(cfg.Name, hidden)
		t.window = self.main
		local tab = setmetatable(t, Tab)
		return tab
	end
	function Win:CreateState(cfg)
		local key = "State>" .. tostring(cfg.Name)
		local value = cfg.Default == true
		if store[key] ~= nil then value = store[key] == true end
		local subs = newSignalList()
		local st = {Name = cfg.Name}
		function st.Get() return value end
		function st.Set(_, v)
			v = v == true
			if v == value then return end
			value = v; setStored(key, v); subs.Fire(v)
		end
		function st.Subscribe(_, fn) return subs.Connect(fn) end
		lib.states[cfg.Name] = st
		return st
	end
	function Win:GetState(name) return lib.states[name] end
	function Win:CreateExclusiveGroup(cfg) return {members = {}, max = cfg.MaxActive or 1, Name = cfg.Name} end

	function lib:CreateWindow(cfg)
		local vp = workspace.CurrentCamera and workspace.CurrentCamera.ViewportSize or Vector2.new(800, 600)
		local mw = math.min(480, math.max(340, vp.X - 24))
		local mh = math.min(370, math.max(240, vp.Y - 60))
		local main = newWindow({name = "main", frameName = "Main", title = "Sources Hub", subtitle = "discord.gg/sourceshubs", subtitleCopy = "discord.gg/sourceshubs", w = mw, h = mh,
			pos = UDim2.new(0.5, -math.floor(mw / 2), 0.5, -math.floor(mh / 2)), isMain = true, z = 20})
		local events = main
		lib.eventsWindow = main
		lib.newWindow = newWindow
		lib.UI = {C = C, corner = corner, stroke = stroke, label = label, liveGrad = liveGrad,
			addLivingStroke = addLivingStroke, makeSwitch = makeSwitch, gui = gui, Tween = TweenService, drag = drag, Shimmer = lib.Shimmer}
		lib.mainWindow = main
		main.frame.Visible = false
		local w = setmetatable({main = main, events = events}, Win)
		w.defaultTab = setmetatable(main.AddTab(cfg.DefaultTab or "Main"), Tab)
		w.defaultTab.window = main
		main.AddTab("Events", false, "Event")
		return w
	end

	-- ---------- dock (floating quick buttons) ----------
	local function buildDock()
		local SZ, GAP, TOP, RIGHT = 44, 8, 66, 10
		local locked = store["Dock>Locked"] == true
		local defs = {
			{id = "speed", label = "Speed"}, {id = "lock", label = "Lock"},
			
			
		}
		for i, def in ipairs(defs) do
			local col, rw = (i - 1) % 2, math.floor((i - 1) / 2)
			local btn = Instance.new("TextButton", gui)
			btn.Name = "YE_Float_" .. def.id
			btn.Size = UDim2.new(0, SZ, 0, SZ)
			btn.Position = UDim2.new(1, -(SZ * 2 + GAP + RIGHT) + col * (SZ + GAP), 0, TOP + rw * (SZ + GAP))
			btn.BackgroundColor3 = C.ROW; btn.BackgroundTransparency = 0.25; btn.BorderSizePixel = 0
			btn.Text = ""; btn.AutoButtonColor = false; btn.ZIndex = 500; btn.Active = true
			corner(btn, 12); addLivingStroke(btn, 1.5); pressFx(btn)
			local l = Instance.new("TextLabel", btn)
			l.Size = UDim2.new(1, 0, 1, 0); l.BackgroundTransparency = 1; l.Text = def.label
			l.TextColor3 = C.WHITE; l.Font = Enum.Font.GothamBold; l.TextSize = 9; l.TextWrapped = true; l.ZIndex = 501
			liveGrad(l)
			local glow = Instance.new("UIStroke", btn)
			glow.Thickness = 2.5; glow.Color = C.GREEN; glow.Transparency = 1
			glow.ApplyStrokeMode = Enum.ApplyStrokeMode.Border
			local dot = Instance.new("Frame", btn)
			dot.Size = UDim2.new(0, 7, 0, 7); dot.Position = UDim2.new(1, -11, 0, 4)
			dot.BackgroundColor3 = C.GREEN; dot.BorderSizePixel = 0; dot.Visible = false; dot.ZIndex = 502
			corner(dot, 4)
			local function mark(on)
				dot.Visible = on == true
				TweenService:Create(glow, TweenInfo.new(0.25), {Transparency = on == true and 0.45 or 1}):Play()
			end
			local dragging, ds, dp, moved = false, nil, nil, false
			btn.InputBegan:Connect(function(inp)
				if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then
					dragging = not locked; ds = inp.Position; dp = btn.Position; moved = false
				end
			end)
			UIS.InputChanged:Connect(function(inp)
				if not dragging then return end
				if inp.UserInputType == Enum.UserInputType.MouseMovement or inp.UserInputType == Enum.UserInputType.Touch then
					local d = inp.Position - ds
					if d.Magnitude > 4 then moved = true end
					btn.Position = UDim2.new(dp.X.Scale, dp.X.Offset + d.X, dp.Y.Scale, dp.Y.Offset + d.Y)
				end
			end)
			UIS.InputEnded:Connect(function(inp)
				if inp.UserInputType == Enum.UserInputType.MouseButton1 or inp.UserInputType == Enum.UserInputType.Touch then dragging = false end
			end)
			btn.MouseButton1Click:Connect(function()
				if moved then return end
				if def.id == "speed" then
					local hd = lib.handles["Player>Movement>Speed Boost"]
					if hd then hd:Set(not hd.Get(), true) end
				elseif def.id == "lock" then
					locked = not locked; setStored("Dock>Locked", locked); mark(locked)
				end
			end)
			if def.id == "speed" then
				task.spawn(function()
					while btn.Parent do
						local hd = lib.handles["Player>Movement>Speed Boost"]
						mark(hd and hd.Get())
						task.wait(0.5)
					end
				end)
			else
				mark(locked)
			end
		end
	end

	local function importConfig(text)
		text = (tostring(text or ""):gsub("^%s+", ""))
		text = (text:gsub("%s+$", ""))
		local body = text:match("^SHCFG1:(.+)$") or text
		local ok, data = pcall(function() return HttpService:JSONDecode(body) end)
		if not ok or type(data) ~= "table" then return nil, "That is not a valid config" end
		local n = 0
		for key, v in pairs(data) do
			if type(key) == "string" and key ~= "GuideSeen" and key ~= "Dock>Locked" then
				local tv = type(v)
				if tv == "boolean" or tv == "number" or tv == "string" or tv == "table" then
					local h = lib.handles[key]
					if key == "Theme" then
						-- themes were removed: ignore the key
					elseif h and type(h.Set) == "function" then
						if pcall(h.Set, h, v, true) then n = n + 1 end
					elseif key:sub(1, 6) == "State>" then
						local st = lib.states[key:sub(7)]
						if st then pcall(st.Set, st, v); n = n + 1 end
					else
						store[key] = v; n = n + 1
					end
				end
			end
		end
		saveSoon()
		return n
	end

	-- ---------- usage stats (Sources Hub site) ----------
	-- One-way POST to the Sources Hub stats site (members online, total executions): Roblox id and name, game name,
	-- script name and version, once at start and once a minute. The answer is ignored: nothing is loaded or executed
	-- from the site. Config > Usage stats has the switch (on by default) and says what is sent.
	local STATS_URL = "https://sourceshub-stats.vercel.app/api/ping"
	local STATS_SITE = "https://sourceshub-stats.vercel.app"
	local STATS_KEY = "Config>Usage stats>Share usage stats"
	local statsGame
	local function statsSend(kind)
		if store[STATS_KEY] == false then return end
		local genv = typeof(getgenv) == "function" and getgenv() or _G
		local send = genv.request or genv.http_request or (type(genv.syn) == "table" and genv.syn.request) or nil
		local lp = Players.LocalPlayer
		if type(send) ~= "function" or not lp then return end
		if not statsGame then
			statsGame = "Unknown game"
			pcall(function() statsGame = game:GetService("MarketplaceService"):GetProductInfo(game.PlaceId).Name end)
		end
		task.spawn(function()
			pcall(function()
				send({
					Url = STATS_URL, Method = "POST", Headers = {["Content-Type"] = "application/json"},
					Body = HttpService:JSONEncode({uid = lp.UserId, name = lp.Name, place = game.PlaceId, game = statsGame, script = "SourcesHub", v = 1, t = kind}),
				})
			end)
		end)
	end
	local function statsStart()
		statsSend("start")
		task.spawn(function()
			while gui.Parent do
				task.wait(60)
				if gui.Parent then statsSend("beat") end
			end
		end)
	end
	lib.StatsSend = statsSend

	local function buildConfigTab()
		local main = lib.mainWindow
		local raw = main.AddTab("Config", false, "Config")
		raw.window = main
		local tab = setmetatable(raw, Tab)
		local sec = tab:CreateSection({Name = "Share config", Expanded = true})
		sec:CreateText({Name = "How it works", Text = "Press Copy and send the text to a friend. They paste it in the box and press Import: every setting is applied at once."})
		local status
		local function say(t) if status then status:Set(t) end end
		sec:CreateButton({Name = "Copy my config", ButtonText = "Copy", ConfirmText = "Copied", Callback = function()
			local out = {}
			for k, v in pairs(store) do
				if k ~= "GuideSeen" and k ~= "Dock>Locked" then out[k] = v end
			end
			local ok, json = pcall(function() return HttpService:JSONEncode(out) end)
			if not ok then say("Could not read the config"); return end
			local text = "SHCFG1:" .. json
			local copied = pcall(function() setclipboard(text) end)
			say(copied and ("Copied " .. #text .. " characters") or "Clipboard is not available on this executor")
		end})
		local _, row = sec:_slot(56)
		local tb = Instance.new("TextBox", row)
		tb.Name = "ConfigBox"
		tb.Size = UDim2.new(1, -16, 1, -16); tb.Position = UDim2.new(0, 8, 0, 8)
		tb.BackgroundColor3 = C.BG; tb.TextColor3 = C.WHITE; styleText(tb)
		tb.PlaceholderText = "Paste a shared config here"; tb.PlaceholderColor3 = C.DIM
		tb.Text = ""; tb.TextSize = 10; tb.Font = Enum.Font.GothamMedium; tb.BorderSizePixel = 0
		tb.ClearTextOnFocus = false; tb.TextWrapped = true; tb.MultiLine = true
		tb.TextXAlignment = Enum.TextXAlignment.Left; tb.TextYAlignment = Enum.TextYAlignment.Top
		corner(tb, 6); addLivingStroke(tb, 1)
		sec:CreateButton({Name = "Import pasted config", ButtonText = "Import", ConfirmText = "Done", Callback = function()
			local n, err = importConfig(tb.Text)
			if n then say("Imported " .. n .. " settings"); tb.Text = "" else say(err) end
		end})
		status = sec:CreateText({Name = "Status", Text = "Ready"})
		local stat = tab:CreateSection({Name = "Usage stats", Expanded = true})
		stat:CreateText({Name = "What is sent", Text = "Your Roblox name and id, the game name, the script name and version: once at start, then once a minute. The Sources Hub site uses it to show members online and total executions. Nothing else is sent and nothing is loaded from the site."})
		stat:CreateToggle({Name = "Share usage stats", Default = true, Callback = function() end})
		stat:CreateButton({Name = "Stats site", ButtonText = "Copy link", ConfirmText = "Copied", Callback = function()
			pcall(function() setclipboard(STATS_SITE) end)
		end})
	end

	function lib:Finalize(cfg)
		local main = lib.mainWindow
		buildConfigTab()
		main.Select((cfg and cfg.MainTab and cfg.MainTab.name) or main.order[1])
		main.SetOpen(true)
		buildDock()
		task.delay(2, statsStart)
		
		task.delay(3, function() lib.ParticlesOn = true end)
		UIS.InputBegan:Connect(function(inp, gp)
			if gp then return end
			if inp.KeyCode == Enum.KeyCode.RightShift then main.SetOpen(not main.IsOpen()) end
		end)
		-- run every callback once now that all controls exist (restores saved state)
		for _, fn in ipairs(fireAtFinalize) do task.spawn(pcall, fn) end
		table.clear(fireAtFinalize)
	end
	lib.CreateWindow = lib.CreateWindow
end
local SourcesLib = lib


local fn, v, sliced2, defaultTab, Players, RunService, ReplicatedStorage, CoreGui, UserInputService, localPlayer
local networking, slicedfn2, tbl, sliced3, slicedfn3, slicedfn4, tbl2, slicedfn5, slicedfn6, tbl3
local tbl4, slicedfn7, tbl5, sliced4, sliced5, espSection, tbl6, color, sequence, palettes

do
	local CollectionService, ProximityPromptService, sliced6, sliced7, tbl7, tbl8, tbl9

	do
		fn = function(arg)
			local genv = typeof(getgenv) == "function" and getgenv() or _G

			if type(genv.SourcesDebugPrint) == "function" then
				pcall(genv.SourcesDebugPrint, arg)
			end
		end

		v = SourcesLib

		v.ManualQuickDefaults = {
			PinnedFeatures = { "Player > Movement > Speed Boost", "Player > Movement > Boost Speed" },
			Keybinds = { ["Player > Movement > Speed Boost"] = "Q" },
			PinGroups = {},
			LeftCenterHidden = true,
		}

		sliced2 = v:CreateWindow({ Name = "Sources Hub", DefaultTab = "Farm" })
		defaultTab = sliced2:GetDefaultTab()
		Players = game:GetService("Players")
		RunService = game:GetService("RunService")
		ReplicatedStorage = game:GetService("ReplicatedStorage")
		CoreGui = game:GetService("CoreGui")
		UserInputService = game:GetService("UserInputService")
		CollectionService = game:GetService("CollectionService")
		game:GetService("LocalizationService")
		ProximityPromptService = game:GetService("ProximityPromptService")
		localPlayer = Players.LocalPlayer
		networking = (function()
			local real = ReplicatedStorage:WaitForChild("Packages"):WaitForChild("Networking")
			-- two remote names in the reference source are damaged ("...Finishaide"):
			-- fall back to the remote of the same family whose name has "Finish"
			local function find(name)
				local r = real:FindFirstChild(name)
				if r then return r end
				if type(name) == "string" and name:find("aide", 1, true) then
					local fam = name:match("^(%a+/[%w_]+/)")
					if fam then
						for _, c in ipairs(real:GetChildren()) do
							if c.Name:sub(1, #fam) == fam and c.Name:find("Finish", 1, true) then return c end
						end
					end
				end
				return nil
			end
			return setmetatable({}, {__index = function(_, k)
				if k == "FindFirstChild" then return function(_, n) return find(n) end end
				if k == "WaitForChild" then return function(_, n, t) return find(n) or real:WaitForChild(n, t) end end
				local v = real[k]
				if type(v) == "function" then return function(_, ...) return v(real, ...) end end
				return v
			end})
		end)()

		slicedfn2 = function(arg)
			local ok, result = pcall(function()
				return require(arg())
			end)

			return ok and result or nil
		end

		tbl = {
			EggState = slicedfn2(function()
				return ReplicatedStorage.Client.EggState
			end),
			AreaEggs = slicedfn2(function()
				return ReplicatedStorage.Shared.Types.AreaEggs
			end),
			ToolGameplayGuard = slicedfn2(function()
				return ReplicatedStorage.Client.ToolGameplayGuard
			end),
			Assets = slicedfn2(function()
				return ReplicatedStorage.Data.Assets
			end),
			Guards = slicedfn2(function()
				return ReplicatedStorage.Data.Guards
			end),
			EggRecords = slicedfn2(function()
				return ReplicatedStorage.Shared.Util.EggRecords
			end),
			Mutations = slicedfn2(function()
				return ReplicatedStorage.Shared.Modules.Mutations
			end),
			Save = slicedfn2(function()
				return ReplicatedStorage.Shared.Save
			end),
			FuseKernel = slicedfn2(function()
				return ReplicatedStorage.Shared.Util.FuseKernel
			end),
			AreaEggCycle = slicedfn2(function()
				return ReplicatedStorage.Shared.Util.AreaEggCycle
			end),
			AreaEggResetWall = slicedfn2(function()
				return ReplicatedStorage.Client.AreaEggResetWall
			end),
			AreaEggResetCycle = slicedfn2(function()
				return ReplicatedStorage.Data.AreaEggResetCycle
			end),
			Gears = slicedfn2(function()
				return ReplicatedStorage.Data.Gears
			end),
			Areas = slicedfn2(function()
				return ReplicatedStorage.Data.Areas
			end),
			LimitedEgg = slicedfn2(function()
				return ReplicatedStorage.Data.LimitedEgg
			end),
			BrainrotEgg = slicedfn2(function()
				return ReplicatedStorage.Data.BrainrotEgg
			end),
			MonsterEgg = slicedfn2(function()
				return ReplicatedStorage.Data.MonsterEgg
			end),
		}

		local save = tbl.Save

		if type(save) == "table" and (type(save.Get) ~= "function" or type(save.FieldSignal) ~= "function") then
			tbl.Save = setmetatable({
				Get = type(save.Get) == "function" and save.Get or save.Peek,
				FieldSignal = type(save.FieldSignal) == "function" and save.FieldSignal or save.Watch,
			}, { __index = save })
		end

		local function slicedfn9()
			if typeof(gethui) == "function" then
				local ok, result = pcall(gethui)
				if ok and typeof(result) == "Instance" then
					return result
				end
			end

			return CoreGui
		end

		sliced3 = slicedfn9()

		do
			local sliced8 = Random.new()
			local str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

			slicedfn3 = function()
				local sliced9 = sliced8:NextInteger(12, 20)
				local sliced10 = table.create(sliced9)

				for i = 1, sliced9 do
					local sliced11 = sliced8:NextInteger(1, #str)
					sliced10[i] = string.sub("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", sliced11, sliced11)
				end

				return table.concat(sliced10)
			end
		end

		do
			local tbl10 = {}

			slicedfn4 = function(arg)
				table.insert(tbl10, arg)
			end

			tbl2 = {}

			slicedfn5 = function(arg, arg2)
				local n = 1000
				local slicedn2 = 3
				local slicedn3 = 12

				local function slicedfn10(arg3)
					if arg3 <= 0 then
						return 0
					end
					local slicedn4 = 10 ^ (math.floor(math.log10(arg3)) - 2)
					return math.floor(arg3 / slicedn4 + 0.5) * slicedn4
				end

				local function slicedfn11(arg3)
					local slicedn4 = math.clamp(tonumber(arg3) or 0, 0, 1000)
					if slicedn4 <= 0 then
						return 0
					end
					return slicedfn10(10 ^ (slicedn2 + (slicedn3 - slicedn2) * slicedn4 / n))
				end

				local function slicedfn12(arg3)
					local slicedn4 = tonumber(arg3) or 0
					if slicedn4 <= 0 then
						return 0
					end
					local slicedn5 = slicedn3 - slicedn2
					return math.clamp(math.floor((math.log10(slicedn4) - slicedn2) / slicedn5 * n * 100 + 0.5) / 100, 0, 1000)
				end

				local function slicedfn13(arg3)
					local str = string.format(arg3 >= 100 and "%.0f" or (arg3 >= 10 and "%.1f" or "%.2f"), arg3)

					if string.find(str, ".", 1, true) then
						str = string.gsub(string.gsub(str, "0+$", ""), "%.$", "")
					end

					return str
				end

				local function slicedfn14(arg3)
					local sliced8 = slicedfn11(arg3)
					if sliced8 <= 0 then
						return "Off"
					end

					if sliced8 < 1000000 then
						return slicedfn13(sliced8 / 1000) .. " K/s"
					end

					if sliced8 < 1e9 then
						return slicedfn13(sliced8 / 1000000) .. " M/s"
					end
					return slicedfn13(sliced8 / 1e9) .. " B/s"
				end

				local function slicedfn15(arg3)
					local sliced8 = slicedfn11(arg3)
					if sliced8 <= 0 then
						return "0"
					end

					if sliced8 < 1000000 then
						return slicedfn13(sliced8 / 1000) .. "k"
					end
					return (string.gsub(string.gsub(string.format("%.3f", sliced8 / 1000000), "0+$", ""), "%.$", ""))
				end

				local tbl11 = { k = 1000, m = 1000000, b = 1e9, t = 1e12 }

				local function slicedfn16(arg3)
					local sliced8 = string.gsub(string.lower(string.gsub(tostring(arg3 or ""), "[%s,/]", "")), "s$", "")
					if sliced8 == "" or sliced8 == "off" then
						return 0
					end
					local sliced9, sliced10 = string.match(sliced8, "^([%d%.]+)([kmbt]?)$")
					local num = tonumber(sliced9)
					if not num then
						return nil
					end
					return slicedfn12(num * (tbl11[sliced10] or 1000000))
				end

				local sliced8 = arg:CreateSlider({
					Name = arg2.Name,
					Note = arg2.Note,
					SubOf = arg2.SubOf,
					Min = 0,
					Max = n,
					Default = slicedfn12(arg2.Default or 0),
					AllowDecimals = true,
					Increment = 0.01,
					ValueFormat = slicedfn14,
					ValueParse = slicedfn16,
					Callback = function(arg3)
						if type(arg2.OnRaw) == "function" then
							arg2.OnRaw(slicedfn11(arg3))
						end
					end,
				})

				local value = type(sliced8) == "table" and rawget(sliced8, "Instance") or nil

				if typeof(value) == "Instance" then
					for _, descendant in ipairs(value:GetDescendants()) do
						if descendant:IsA("TextBox") then
							local connection = descendant.Focused:Connect(function()
								task.defer(function()
									if descendant:IsFocused() then
										local ok, result = pcall(sliced8.Get, sliced8)
										descendant.Text = slicedfn15(ok and result or 0)
										descendant.CursorPosition = #descendant.Text + 1
										descendant.SelectionStart = 1
									end
								end)
							end)

							slicedfn4(function()
								pcall(function()
									connection:Disconnect()
								end)
							end)
						end
					end
				end

				if type(arg2.Legacy) == "string" and type(arg2.SectionName) == "string" then
					table.insert(tbl2, { Handle = sliced8, Name = arg2.Name, Legacy = arg2.Legacy, Section = arg2.SectionName, StepOf = slicedfn12 })
				end

				return sliced8
			end

			local text = "All"

			slicedfn6 = function(arg)
				if type(arg) ~= "table" then
					return arg
				end
				local value = rawget(arg, "Instance")
				if typeof(value) ~= "Instance" then
					return arg
				end
				local flag = false

				local function slicedfn10(arg2)
					if flag then
						return
					end

					if arg2.Text == "None" then
						flag = true
						arg2.Text = text
						flag = false
					end
				end

				local function slicedfn11(descendant)
					if not descendant:IsA("TextLabel") or descendant.Name ~= "Value" then
						return
					end
					slicedfn10(descendant)

					local connection = descendant:GetPropertyChangedSignal("Text"):Connect(function()
						slicedfn10(descendant)
					end)

					slicedfn4(function()
						pcall(function()
							connection:Disconnect()
						end)
					end)
				end

				for _, descendant in ipairs(value:GetDescendants()) do
					slicedfn11(descendant)
				end

				local connection = value.DescendantAdded:Connect(slicedfn11)

				slicedfn4(function()
					pcall(function()
						connection:Disconnect()
					end)
				end)

				return arg
			end

			local genv = typeof(getgenv) == "function" and getgenv() or _G
			local SourcesHubSaeCleanup = genv.SourcesHubSaeCleanup

			if type(SourcesHubSaeCleanup) == "function" then
				pcall(SourcesHubSaeCleanup)
			end

			genv.SourcesHubSaeCleanup = function()
				for i = #tbl10, 1, -1 do
					pcall(tbl10[i])
				end

				table.clear(tbl10)
			end
		end

		do
			local n = 0
			local slicedfn10 = nil

			slicedfn10 = function(arg, arg2)
				local slicedn2 = arg2 or 0

				if type(arg) == "table" then
					if slicedn2 > 3 then
						return
					end
					local slicedn3 = 0

					for k, sliced8 in pairs(arg) do
						slicedn3 += 1

						if not (slicedn3 > 20) then
							slicedfn10(k, slicedn2 + 1)
							slicedfn10(sliced8, slicedn2 + 1)
							continue
						end

						break
					end
				elseif typeof(arg) == "Instance" then
					pcall(arg.GetFullName, arg)
				else
					n += #tostring(arg)
				end
			end

			local tbl10 = {}

			local function slicedfn11(arg)
				tbl10[#tbl10 + 1] = arg
			end

			local function slicedfn12()
				for _, sliced8 in ipairs(tbl10) do
					pcall(function()
						sliced8:Disconnect()
					end)
				end

				table.clear(tbl10)
			end

			local function SourcesToolKeeper()
				slicedfn12()

				for _, sliced8 in ipairs({
					"RE/GearSatchel/Lost",
					"RE/GearSatchel/Gained",
					"RE/RigSync/ProbeSatchel",
					"RE/RigSync/SeedSatchel",
					"RE/RigSync/CorrectionBegan",
					"RE/RigSync/Refresh",
					"RE/ToolTrigger/Trigger",
					"RE/BatSwing/Trigger",
				}) do
					local sliced9 = networking:FindFirstChild(sliced8)

					if sliced9 and sliced9:IsA("RemoteEvent") then
						slicedfn11(sliced9.OnClientEvent:Connect(function(...)
							slicedfn10({ ... })
						end))
					end
				end

				local function slicedfn13(arg)
					if not arg then
						return
					end

					slicedfn11(arg.ChildRemoved:Connect(function(child)
						if child:IsA("Tool") then
							slicedfn10({ child.Name, child.Parent })
						end
					end))

					slicedfn11(arg.ChildAdded:Connect(function(child)
						if child:IsA("Tool") then
							slicedfn10({ child.Name })
						end
					end))
				end

				slicedfn13(localPlayer:FindFirstChildOfClass("Backpack"))

				slicedfn11(localPlayer.ChildAdded:Connect(function(child)
					if child:IsA("Backpack") then
						slicedfn13(child)
					end
				end))

				task.spawn(function()
					pcall(function()
						local sliced8 = tbl.Save.Get()
						slicedfn10({ sliced8.GearInventory, sliced8.Inventory }, 2)
					end)

					if type(getgc) == "function" then
						pcall(function()
							for _, sliced8 in ipairs(getgc(false)) do
								if type(sliced8) == "function" and islclosure(sliced8) then
									pcall(debug.info, sliced8, "n")
								end
							end
						end)
					end
				end)
			end
			;(typeof(getgenv) == "function" and getgenv() or _G).SourcesToolKeeper = SourcesToolKeeper
			task.defer(SourcesToolKeeper)
			slicedfn4(slicedfn12)
		end

		do
			local n = 0.35
			local slicedn2 = 5
			local tbl10 = {}
			local flag = true

			tbl3 = {
				Add = function(arg)
					local tbl11 = { Run = arg, Gap = n, Idle = slicedn2, Repeat = false, Hold = 0 }
					table.insert(tbl10, tbl11)
					return tbl11
				end,
				Wake = function()
					flag = true
				end,
				Backoff = function(arg, arg2)
					if arg then
						arg.Hold = tonumber(arg2) or 6
					end
				end,
			}

			local connection = RunService.Heartbeat:Connect(function(deltaTime)
				local sliced8 = flag
				flag = false

				for _, sliced9 in ipairs(tbl10) do
					sliced9.Gap = sliced9.Gap + deltaTime
					sliced9.Idle = sliced9.Idle + deltaTime

					if sliced9.Hold > 0 then
						sliced9.Hold = sliced9.Hold - deltaTime
					else
						local flag2 = sliced9.Gap >= n
						local repeat_

						if flag2 then
							repeat_ = sliced8 or sliced9.Repeat or sliced9.Idle >= slicedn2
						else
							repeat_ = flag2
						end

						if repeat_ then
							sliced9.Gap = 0
							sliced9.Idle = 0
							local ok, result = pcall(sliced9.Run, sliced9)
							sliced9.Repeat = ok and result == true
						end
					end
				end
			end)

			slicedfn4(function()
				connection:Disconnect()
			end)
		end

		sliced6 = defaultTab:CreateSection({ Name = "Dr Scramble Lab & Mech", Expanded = false })
		local sliced8 = defaultTab:CreateSection({ Name = "Auto Steal", Expanded = true })
		local sliced9 = defaultTab:CreateSection({ Name = "Auto Place Egg", Expanded = false })
		local sliced10 = defaultTab:CreateSection({ Name = "Auto Treadmill", Expanded = false })
		local sliced11 = defaultTab:CreateSection({ Name = "Auto Hatch & Equip", Expanded = false })
		local sliced12 = defaultTab:CreateSection({ Name = "Auto Sell", Expanded = false })
		local sliced13 = defaultTab:CreateSection({ Name = "Auto Fuse Machine", Expanded = false })
		sliced7 = defaultTab:CreateSection({ Name = "Auto Favorite", Expanded = false })
		tbl7 = { Paused = false }

		do
			local n = 0.5
			local sliced14 = nil
			local tbl10 = nil
			local tbl11 = {}
			local flag = false
			local slicedn2 = 0

			local function slicedfn10()
				for i = #tbl11, 1, -1 do
					local sliced15 = tbl11[i]

					if sliced15 and sliced15.Connected then
						sliced15:Disconnect()
					end

					tbl11[i] = nil
				end
			end

			local function slicedfn11()
				slicedfn10()
				local sliced15 = sliced14
				local sliced16 = tbl10
				sliced14 = nil
				tbl10 = nil
				if not sliced15 or not sliced15.Parent or not sliced16 then
					return
				end

				pcall(function()
					sliced15.BreakJointsOnDeath = sliced16.BreakJointsOnDeath
					sliced15.RequiresNeck = sliced16.RequiresNeck
					sliced15:SetStateEnabled(Enum.HumanoidStateType.Dead, sliced16.DeadEnabled)
				end)
			end

			local function slicedfn12(arg)
				if not arg or not arg.Parent then
					return false
				end

				return pcall(function()
					arg.BreakJointsOnDeath = false
					arg.RequiresNeck = false
					arg:SetStateEnabled(Enum.HumanoidStateType.Dead, false)
				end) and arg.BreakJointsOnDeath == false and arg.RequiresNeck == false and arg:GetStateEnabled(Enum.HumanoidStateType.Dead) == false
			end

			local function slicedfn13(arg)
				if tbl7.Paused or arg ~= sliced14 or not arg or not arg.Parent or flag then
					return false
				end
				local maxHealth = arg.MaxHealth
				if maxHealth <= 0 then
					return false
				end

				if maxHealth == math.huge or arg.Health >= maxHealth then
					return true
				end
				flag = true

				local ok = pcall(function()
					arg.Health = maxHealth
				end)

				flag = false
				return ok and arg.Health >= maxHealth
			end

			local function slicedfn14(arg)
				if arg == sliced14 and arg and arg.Parent then
					return true
				end
				slicedfn11()
				if not arg or not arg:IsA("Humanoid") or not arg.Parent then
					return false
				end
				sliced14 = arg

				tbl10 = {
					BreakJointsOnDeath = arg.BreakJointsOnDeath,
					RequiresNeck = arg.RequiresNeck,
					DeadEnabled = arg:GetStateEnabled(Enum.HumanoidStateType.Dead),
				}

				if not slicedfn12(arg) then
					slicedfn11()
					return false
				end
				slicedfn13(arg)

				tbl11[#tbl11 + 1] = arg.HealthChanged:Connect(function()
					slicedfn13(arg)
				end)

				tbl11[#tbl11 + 1] = arg:GetPropertyChangedSignal("MaxHealth"):Connect(function()
					slicedfn13(arg)
				end)

				tbl11[#tbl11 + 1] = arg.StateChanged:Connect(function(old, new)
					if new == Enum.HumanoidStateType.Dead and not tbl7.Paused then
						slicedfn12(arg)
						slicedfn13(arg)
					end
				end)

				slicedn2 = os.clock()
				return true
			end

			local function slicedfn15()
				local character = localPlayer.Character
				return character and character:FindFirstChildOfClass("Humanoid") or nil
			end

			local connection = localPlayer.CharacterAdded:Connect(function()
				task.defer(function()
					slicedfn14(slicedfn15())
				end)
			end)

			local connection2 = RunService.Heartbeat:Connect(function()
				local now = os.clock()
				if tbl7.Paused or now - slicedn2 < n then
					return
				end
				slicedn2 = now
				local sliced15 = slicedfn15()
				if sliced15 ~= sliced14 then
					slicedfn14(sliced15)
					return
				end

				if sliced15 then
					slicedfn12(sliced15)
					slicedfn13(sliced15)
				end
			end)

			task.defer(function()
				slicedfn14(slicedfn15())
			end)

			slicedfn4(function()
				if connection then
					connection:Disconnect()
				end

				if connection2 then
					connection2:Disconnect()
				end

				slicedfn11()
			end)
		end

		local tbl10 = { "bat", "katana", "axe", "staff", "club", "hammer", "sword", "blade" }

		tbl4 = {
			Steal = { Active = false, LastFinishedAt = 0, Carrying = false },
			SafeCarry = {
				Enabled = true,
				SkipUnsafe = false,
				WaitGuard = false,
				SameSpeedBigEggs = false,
				Blocked = {},
				StretchSeconds = 6,
				BeatGuard = false,
				SlowUntil = 0,
				SlowFactor = 0.3,
				LineDrop = false,
				Stops = 3,
				StopTime = 0.7,
				LineGap = 12,
				LineWait = 15,
				DirectBudget = 450,
				DirectMargin = 1.2,
				CrossNow = false,
				CrossSpeed = 231,
				PickupSpeed = 154,
				HopRatio = 1.515,
				CrossRatio = 1,
				PickupRatio = 0.667,
				FarFromLine = 150,
				DropDelay = 0.19,
				LineApproach = 0.97,
				ReJump = true,
				ShakeTime = 0,
				SnapPickup = false,
				Hops = true,
				HopStep = 350,
				HopGap = 0.1,
				HopLift = 42,
				HopStop = 48,
				GetUp = true,
				ShakeInside = 1,
				CarryScale = 1,
				EasyRatio = 1.3,
				LastSkip = nil,
				Category = nil,
				PlanOk = true,
				LightMult = 0.96,
				Height = 70,
				ClimbShare = 0.5,
				Approach = "Run",
				RunSpeed = 1,
				RunWait = 0,
				RunAnimate = true,
				RunHeight = 50,
				SnapLimit = 90,
				StraightRun = true,
				RunStyle = "Velocity",
				CarryStyle = "Velocity",
				SpeedJitter = 0.08,
				Wobble = 0,
				LaneOffset = 0,
				JumpsPerMinute = 0,
				PausesPerMinute = 0,
				ReactMin = 0.2,
				ReactMax = 0.6,
				CarryReact = 0,
				SpeedRatio = 1.5,
				ExcessSeconds = 5.5,
				GuardMargin = 4,
				GuardRatio = 1.06,
				MinRatio = 1.1,
				BaseWait = 6.5,
				FreeJump = 1500,
				WaitRate = 0.9,
				RecoverTries = math.huge,
				GuessMult = 0.93,
				CarryRatio = 0.9,
				Mult = 1,
				Seen = {},
				JumpDistance = 0,
				JumpAt = 0,
				LastDelivered = 0,
				LastFailed = 0,
				Handle = nil,
			},
			Movement = {
				Owner = nil,
				PlaceWanted = false,
				StealFirst = false,
				MutationWanted = false,
				FracturedWanted = false,
			},
			AntiGuard = {
				Enabled = false,
				Busy = false,
				BusySince = 0,
				HitArms = 0,
				Handle = nil,
				Render = nil,
			},
			IsBatTool = function(arg)
				if typeof(arg) ~= "Instance" or not arg:IsA("Tool") then
					return false
				end

				if arg:GetAttribute("IsBat") == true then
					return true
				end
				local attribute = arg:GetAttribute("GearName")

				if type(attribute) == "string" then
					local gears = tbl.Gears
					local directory = type(gears) == "table" and gears.Directory or nil
					local flag = type(directory) == "table" and directory[attribute] or nil
					return type(flag) == "table" and flag.BatControllerData ~= nil
				end

				if arg:GetAttribute("ItemType") ~= nil then
					return false
				end
				local sliced14 = string.lower(arg.Name)

				for _, sliced15 in ipairs(tbl10) do
					if string.find(sliced14, sliced15, 1, true) then
						return true
					end
				end

				return false
			end,
			FindBat = function()
				local character = localPlayer.Character
				local tool = character and character:FindFirstChildWhichIsA("Tool")
				if tbl4.IsBatTool(tool) then
					return tool
				end
				local backpack = localPlayer:FindFirstChildOfClass("Backpack")

				if backpack then
					for _, child in ipairs(backpack:GetChildren()) do
						if tbl4.IsBatTool(child) then
							return child
						end
					end
				end

				if character then
					for _, child in ipairs(character:GetChildren()) do
						if tbl4.IsBatTool(child) then
							return child
						end
					end
				end

				return nil
			end,
			IsNight = function()
				local areaEggCycle = tbl.AreaEggCycle
				if type(areaEggCycle) ~= "table" or type(areaEggCycle.IsNightPhase) ~= "function" then
					return false
				end
				local ok, result = pcall(areaEggCycle.IsNightPhase, workspace:GetServerTimeNow())
				return ok and result == true
			end,
			WallSealed = function()
				local areaEggResetWall = tbl.AreaEggResetWall
				if type(areaEggResetWall) ~= "table" or type(areaEggResetWall.IsSealed) ~= "function" then
					return false
				end
				local ok, result = pcall(areaEggResetWall.IsSealed)
				return ok and result == true
			end,
			WallOpenDelay = function()
				local areaEggResetCycle = tbl.AreaEggResetCycle
				if type(areaEggResetCycle) ~= "table" then
					return 5
				end
				return (tonumber(areaEggResetCycle.WallCountdownDelayAfterDayStartsSeconds) or 2) + (tonumber(areaEggResetCycle.WallCountdownSeconds) or 3)
			end,
			ClaimMovement = function(owner)
				local movement = tbl4.Movement
				if movement.Owner == nil or movement.Owner == owner or movement.Owner == "treadmill" and owner ~= "treadmill" or movement.Owner == "scramble" and owner == "steal" then
					movement.Owner = owner
					return true
				end
				return false
			end,
			ReleaseMovement = function(arg)
				if tbl4.Movement.Owner == arg then
					tbl4.Movement.Owner = nil
				end
			end,
		}

		do
			local shieldMethods = { "Humanoid Swap", "Disable Monitor" }
			tbl4.ShieldMethods = shieldMethods
			local sliced14 = shieldMethods[1]
			local tbl11 = {}
			local tbl12 = {}
			local connection = nil
			local n = 0
			local tbl13 = { Original = nil, Clone = nil, Links = {} }
			local connection2 = nil
			local tbl14 = {}

			local function slicedfn10()
				for _, sliced15 in ipairs(tbl14) do
					task.defer(function()
						pcall(sliced15)
					end)
				end
			end

			tbl4.OnHumanoidChanged = function(arg)
				table.insert(tbl14, arg)
				local tbl15

				tbl15 = {
					Connected = true,
					Disconnect = function()
						tbl15.Connected = false
						local sliced15 = table.find(tbl14, arg)

						if sliced15 then
							table.remove(tbl14, sliced15)
						end
					end,
				}

				return tbl15
			end

			local function slicedfn11(humanoid)
				pcall(function()
					local playerScripts = localPlayer:FindFirstChild("PlayerScripts")
					local playerModule = playerScripts and playerScripts:FindFirstChild("PlayerModule")

					if playerModule then
						local controls = require(playerModule):GetControls()

						if type(controls) == "table" then
							controls.humanoid = humanoid
						end
					end
				end)
			end

			local function slicedfn12(arg)
				local animate = arg and arg:FindFirstChild("Animate")

				if animate and animate:IsA("LocalScript") then
					task.spawn(function()
						animate.Enabled = false
						task.wait()
						animate.Enabled = true
					end)
				end
			end

			local function slicedfn13()
				for _, link in ipairs(tbl13.Links) do
					pcall(function()
						link:Disconnect()
					end)
				end

				table.clear(tbl13.Links)
			end

			tbl4.UndoSwap = function()
				slicedfn13()
				local character = localPlayer.Character
				local original = tbl13.Original
				local clone = tbl13.Clone
				local sliced15 = tbl13
				tbl13.Original = nil
				sliced15.Clone = nil

				if original and clone and character and original.Parent == nil and clone.Parent == character then
					original.Parent = character
					workspace.CurrentCamera.CameraSubject = original
					slicedfn11(original)

					pcall(function()
						clone:Destroy()
					end)

					slicedfn12(character)
					slicedfn10()
				end
			end

			local tbl15 = {
				[Enum.HumanoidStateType.Running] = true,
				[Enum.HumanoidStateType.RunningNoPhysics] = true,
				[Enum.HumanoidStateType.Landed] = true,
			}

			tbl4.Grounded = function(arg)
				if not arg then
					local character = localPlayer.Character
					arg = character and character:FindFirstChildOfClass("Humanoid")
				end

				if not arg or arg.Health <= 0 or arg.FloorMaterial == Enum.Material.Air then
					return false
				end
				return tbl15[arg:GetState()] == true
			end

			tbl4.ShieldPaused = false

			tbl4.WalkSpeed = function()
				local character = localPlayer.Character
				character = character and character:FindFirstChildOfClass("Humanoid")
				character = character and character.WalkSpeed or 16
				local original = tbl13.Original

				if original and original.Health > 0 then
					character = math.min(character, original.WalkSpeed)
				end

				local ok, result = pcall(function()
					local leaderstats = localPlayer:FindFirstChild("leaderstats")
					leaderstats = leaderstats and leaderstats:FindFirstChild("Speed")
					local TreadmillUtil = require(ReplicatedStorage.Shared.Util.TreadmillUtil)
					return leaderstats and TreadmillUtil.SpeedPowerToWalkSpeed(leaderstats.Value) or nil
				end)

				local slicedn2

				if ok and tonumber(result) and result > 0 then
					slicedn2 = math.min(character, result)
				else
					slicedn2 = character
				end

				return slicedn2
			end

			local function slicedfn14()
				local character = localPlayer.Character
				local humanoid = character and character:FindFirstChildOfClass("Humanoid")
				if not humanoid or humanoid.Health <= 0 then
					return
				end

				if tbl13.Clone and tbl13.Clone.Parent == character then
					return
				end

				if not tbl4.Grounded(humanoid) then
					return
				end
				local clone = humanoid:Clone()
				humanoid.Parent = nil
				clone.Parent = character
				workspace.CurrentCamera.CameraSubject = clone
				slicedfn11(clone)
				slicedfn12(character)
				local sliced15 = tbl13
				tbl13.Original = humanoid
				sliced15.Clone = clone
				slicedfn10()

				table.insert(tbl13.Links, humanoid:GetPropertyChangedSignal("WalkSpeed"):Connect(function()
					if clone.Parent ~= nil then
						clone.WalkSpeed = humanoid.WalkSpeed
					end
				end))

				local animator = humanoid:FindFirstChildOfClass("Animator")
				local animator2 = clone:FindFirstChildOfClass("Animator")

				if animator and animator2 then
					table.insert(tbl13.Links, animator.AnimationPlayed:Connect(function(arg)
						local animation = arg.Animation
						if not animation or clone.Parent == nil then
							return
						end

						local ok, result = pcall(function()
							return animator2:LoadAnimation(animation)
						end)

						if not ok or not result then
							return
						end

						pcall(function()
							result.Priority = arg.Priority
							result.Looped = arg.Looped
							local speed = arg.Speed
							result:Play(0.05, math.max(arg.WeightTarget, 0.01), speed)
						end)

						local connection3 = nil

						connection3 = arg.Stopped:Connect(function()
							connection3:Disconnect()

							pcall(function()
								result:Stop(0.1)
							end)
						end)
					end))
				end

				table.insert(tbl13.Links, clone.Died:Connect(function()
					slicedfn13()
					local sliced16 = tbl13
					tbl13.Original = nil
					sliced16.Clone = nil
					local character2 = localPlayer.Character

					if character2 and humanoid.Parent == nil then
						humanoid.Parent = character2
						workspace.CurrentCamera.CameraSubject = humanoid
						slicedfn11(humanoid)
						slicedfn10()
					end

					pcall(function()
						clone:Destroy()
					end)

					humanoid.Health = 0
				end))
			end

			local function slicedfn15()
				if type(getconnections) ~= "function" then
					return
				end

				for _, sliced15 in ipairs({ RunService.Heartbeat, RunService.PreSimulation, RunService.PostSimulation }) do
					local ok, result = pcall(getconnections, sliced15)

					if ok and type(result) == "table" then
						for _, sliced16 in ipairs(result) do
							local ok2, result2 = pcall(function()
								return sliced16.Function
							end)

							local flag = ok2 and type(result2) == "function"
							local flag2 = false
							local result3 = nil

							if flag then
								flag2, result3 = pcall(debug.info, result2, "s")
							end

							if flag2 and string.find(tostring(result3), "UGI", 1, true) then
								local ok3, result4 = pcall(function()
									return sliced16.Enabled
								end)

								if not ok3 or result4 ~= false then
									if pcall(function()
										sliced16:Disable()
									end) then
										table.insert(tbl12, sliced16)
									end
								end
							end
						end
					end
				end
			end

			local function slicedfn16()
				if connection then
					connection:Disconnect()
					connection = nil
				end

				if connection2 then
					connection2:Disconnect()
					connection2 = nil
				end

				for _, sliced15 in ipairs(tbl12) do
					pcall(function()
						sliced15:Enable()
					end)
				end

				table.clear(tbl12)
			end

			local function slicedfn17()
				if tbl4.ShieldPaused then
					return
				end

				if sliced14 == shieldMethods[1] then
					slicedfn14()
				else
					slicedfn15()
				end
			end

			local function slicedfn18()
				slicedfn17()
				n = 0

				connection = RunService.Heartbeat:Connect(function(deltaTime)
					n += deltaTime
					local character = localPlayer.Character
					local flag = sliced14 == shieldMethods[1]

					if flag then
						flag = not (tbl13.Clone and character and tbl13.Clone.Parent == character)
					end

					if (flag and 0.25 or 3) <= n then
						n = 0
						slicedfn17()
					end
				end)

				connection2 = localPlayer.CharacterAdded:Connect(function(character)
					slicedfn13()
					local sliced15 = tbl13
					tbl13.Original = nil
					sliced15.Clone = nil
					if sliced14 ~= shieldMethods[1] then
						return
					end

					task.spawn(function()
						character:WaitForChild("Humanoid", 10)
						task.wait(1)

						if connection and localPlayer.Character == character then
							slicedfn17()
						end
					end)
				end)
			end

			tbl4.Swapped = function()
				if sliced14 ~= shieldMethods[1] then
					return true
				end
				local character = localPlayer.Character
				return tbl13.Clone ~= nil and character ~= nil and tbl13.Clone.Parent == character
			end

			tbl4.Shield = function(arg, arg2)
				tbl11[arg] = arg2 == true or nil
				if next(tbl11) == nil then
					slicedfn16()
					return
				end

				if connection then
					return
				end
				slicedfn18()
			end

			tbl4.SetShieldMethod = function(arg)
				if not table.find(shieldMethods, arg) or arg == sliced14 then
					return
				end
				local flag = connection ~= nil
				slicedfn16()
				sliced14 = arg

				if flag and next(tbl11) ~= nil then
					slicedfn18()
				end
			end

			slicedfn4(slicedfn16)
		end

		tbl4.Shield("load", true)

		tbl4.Toggle = function(arg, arg2)
			if type(arg) ~= "table" then
				return arg2 == true
			end

			local ok, result = pcall(function()
				local controller = arg._controller
				return type(controller) == "table" and type(controller.GetValue) == "function" and controller.GetValue()
			end)

			if ok and type(result) == "boolean" then
				return result
			end

			for _, sliced14 in ipairs({ "Get", "GetValue" }) do
				local ok2, result2 = pcall(function()
					return arg[sliced14]
				end)

				if ok2 and type(result2) == "function" then
					local ok3, result3 = pcall(result2, arg)
					if ok3 and type(result3) == "boolean" then
						return result3
					end
				end
			end

			return arg2 == true
		end

		tbl4.Root = function()
			local character = localPlayer.Character
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			return humanoidRootPart and humanoidRootPart:IsDescendantOf(workspace) and humanoidRootPart or nil
		end

		tbl4.PlacedPoints = function()
			local placedEggRenders = workspace:FindFirstChild("PlacedEggRenders")
			local tbl11 = {}
			if not placedEggRenders then
				return tbl11
			end
			local str = tostring(localPlayer.UserId)

			for _, child in ipairs(placedEggRenders:GetChildren()) do
				if string.find(child.Name, str, 1, true) then
					local ok, result = pcall(function()
						return child:IsA("Model") and child:GetPivot() or child.CFrame
					end)

					if ok then
						table.insert(tbl11, result.Position)
					end
				end
			end

			return tbl11
		end

		tbl4.OwnPlot = function()
			local plots = workspace:FindFirstChild("Plots")
			if not plots then
				return nil
			end

			for _, child in ipairs(plots:GetChildren()) do
				local plotSign = child:FindFirstChild("PlotSign")
				plotSign = plotSign and plotSign:FindFirstChild("PlayerPlotSign")
				plotSign = plotSign and plotSign:FindFirstChild("Frame")
				plotSign = plotSign and plotSign:FindFirstChild("PlayerName")

				if plotSign and plotSign:IsA("TextLabel") then
					local sliced14 = string.lower(plotSign.Text)
					if sliced14 == string.lower(localPlayer.Name) or sliced14 == string.lower(localPlayer.DisplayName) then
						return child
					end
				end
			end

			return nil
		end

		local function slicedfn10()
			local sliced14 = tbl4.PlacedPoints()
			if #sliced14 == 0 then
				return nil
			end
			local vector = Vector3.zero

			for _, sliced15 in ipairs(sliced14) do
				vector += sliced15
			end

			return vector / #sliced14
		end

		tbl4.PenAnchor = function()
			local sliced14 = slicedfn10()
			if sliced14 then
				return sliced14
			end
			local sliced15 = tbl4.OwnPlot()
			if not sliced15 then
				return nil
			end
			local toUpdate = sliced15:FindFirstChild("ToUpdate")
			local starterPen = toUpdate and toUpdate:FindFirstChild("StarterPen") or sliced15:FindFirstChild("CenterPoint")
			if not starterPen then
				return nil
			end

			local ok, result = pcall(function()
				return starterPen:IsA("Model") and starterPen:GetPivot() or starterPen.CFrame
			end)

			return ok and result.Position or nil
		end

		tbl4.Plot = function()
			local sliced14 = tbl4.OwnPlot()
			if sliced14 then
				return sliced14
			end
			local plots = workspace:FindFirstChild("Plots")
			local sliced15 = slicedfn10()
			if not plots or not sliced15 then
				return nil
			end
			local huge = math.huge
			local sliced16 = nil

			for _, child in ipairs(plots:GetChildren()) do
				local ok, result, result2 = pcall(function()
					return child:GetBoundingBox()
				end)

				if ok and result and result2 then
					local sliced17 = result:PointToObjectSpace(sliced15)
					local n = result2.X / 2
					local flag = math.abs(sliced17.X) <= n

					if flag then
						local slicedn2 = result2.Z / 2
						flag = math.abs(sliced17.Z) <= slicedn2
					end

					if flag then
						return child
					end
					local magnitude = (result.Position - sliced15).Magnitude

					if magnitude < huge then
						sliced16 = child
						huge = magnitude
					end
				end
			end

			if sliced16 and huge <= 60 then
				return sliced16
			end
			return nil
		end

		tbl4.Belt = function()
			local sliced14 = tbl4.Plot()
			if not sliced14 then
				return nil
			end
			local treadmillBottom = sliced14:FindFirstChild("TreadmillBottom")
			if treadmillBottom and treadmillBottom:IsA("BasePart") then
				return treadmillBottom
			end
			local clientTreadmillRenders = workspace:FindFirstChild("__ClientTreadmillRenders")
			clientTreadmillRenders = clientTreadmillRenders and clientTreadmillRenders:FindFirstChild("TreadmillRender_" .. sliced14.Name)
			local boundingBoxPart = clientTreadmillRenders and (clientTreadmillRenders:FindFirstChild("BoundingBoxPart") or clientTreadmillRenders:IsA("Model") and clientTreadmillRenders.PrimaryPart or clientTreadmillRenders:FindFirstChildWhichIsA("BasePart"))
			if boundingBoxPart then
				return boundingBoxPart
			end
			local treadmillUpgrade = sliced14:FindFirstChild("TreadmillUpgrade")
			return treadmillUpgrade and treadmillUpgrade:FindFirstChildWhichIsA("BasePart") or nil
		end

		tbl4.DistanceTo = function(arg)
			local sliced14 = tbl4.Root()
			if not sliced14 or not arg then
				return math.huge
			end
			return (sliced14.Position - arg).Magnitude
		end

		do
			local tbl11 = {}
			local n = 0

			local function slicedfn11()
				local sliced14 = tbl4.Plot()
				if not sliced14 then
					return {}
				end
				local tbl12 = {}

				for _, sliced15 in ipairs({ "TreadmillBottom", "TreadmillUpgrade" }) do
					local sliced16 = sliced14:FindFirstChild(sliced15)

					if sliced16 then
						if sliced16:IsA("BasePart") then
							table.insert(tbl12, sliced16)
						else
							for _, descendant in ipairs(sliced16:GetDescendants()) do
								if descendant:IsA("BasePart") then
									table.insert(tbl12, descendant)
								end
							end
						end
					end
				end

				local clientTreadmillRenders = workspace:FindFirstChild("__ClientTreadmillRenders")
				clientTreadmillRenders = clientTreadmillRenders and clientTreadmillRenders:FindFirstChild("TreadmillRender_" .. sliced14.Name)

				if clientTreadmillRenders then
					for _, descendant in ipairs(clientTreadmillRenders:GetDescendants()) do
						if descendant:IsA("BasePart") then
							table.insert(tbl12, descendant)
						end
					end
				end

				return tbl12
			end

			local function slicedfn12()
				for _, sliced14 in ipairs(slicedfn11()) do
					if not tbl11[sliced14] then
						tbl11[sliced14] = {
							CFrame = sliced14.CFrame,
							CanTouch = sliced14.CanTouch,
							CanCollide = sliced14.CanCollide,
							Transparency = sliced14.Transparency,
						}

						pcall(function()
							sliced14.CanTouch = false
							sliced14.CanCollide = false
							sliced14.Transparency = 1
							sliced14.CFrame = sliced14.CFrame - Vector3.new(0, 120, 0)
						end)
					end
				end
			end

			local function slicedfn13()
				for k, sliced14 in pairs(tbl11) do
					if k and k.Parent then
						pcall(function()
							k.CFrame = sliced14.CFrame
							k.CanTouch = sliced14.CanTouch
							k.CanCollide = sliced14.CanCollide
							k.Transparency = sliced14.Transparency
						end)
					end
				end

				table.clear(tbl11)
			end

			tbl4.HoldBelt = function()
				n += 1
				slicedfn12()
			end

			tbl4.ReleaseBelt = function()
				n = math.max(0, n - 1)

				if n == 0 then
					slicedfn13()
				end
			end

			tbl4.BeltHeld = function()
				return n > 0
			end

			tbl4.RefreshBeltHide = function()
				if n > 0 then
					slicedfn12()
				end
			end

			slicedfn4(function()
				n = 0
				slicedfn13()
			end)

			tbl4.LeaveBelt = function()
				local rfTreadmillAskDoff = networking:FindFirstChild("RF/Treadmill/AskDoff")

				if rfTreadmillAskDoff and rfTreadmillAskDoff:IsA("RemoteFunction") then
					pcall(rfTreadmillAskDoff.InvokeServer, rfTreadmillAskDoff)
				end
			end

			tbl4.Treadmill = { Riding = false }

			tbl4.ResetBelt = function()
				n = 0
				slicedfn13()
			end

			tbl4.OnBelt = function()
				local sliced14 = tbl4.Belt()
				if not sliced14 or tbl11[sliced14] then
					return false
				end
				local sliced15 = tbl4.Root()
				if not sliced15 then
					return false
				end
				local sliced16 = sliced14.CFrame:PointToObjectSpace(sliced15.Position)
				local slicedn2 = sliced14.Size.X / 2 + 2
				local flag = math.abs(sliced16.X) <= slicedn2

				if flag then
					local slicedn3 = sliced14.Size.Z / 2 + 2
					flag = math.abs(sliced16.Z) <= slicedn3
				end

				return flag and sliced16.Y >= -2 and sliced16.Y <= sliced14.Size.Y / 2 + 8
			end
		end

		tbl4.ExitBelt = function()
			tbl4.Treadmill.Riding = false
			tbl4.LeaveBelt()
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid then
				pcall(function()
					humanoid.Jump = true
					humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
				end)
			end

			task.wait(0.35)
		end

		tbl4.Flying = false
		tbl4.Driving = 0

		tbl4.BeginFlight = function()
			tbl4.Flying = true
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid then
				humanoid.PlatformStand = true

				pcall(function()
					humanoid:ChangeState(Enum.HumanoidStateType.Freefall)
				end)
			end

			return tbl4.Root() ~= nil
		end

		tbl4.SetFlightVelocity = function(assemblyLinearVelocity)
			local sliced14 = tbl4.Root()

			if sliced14 then
				sliced14.AssemblyLinearVelocity = assemblyLinearVelocity
				sliced14.AssemblyAngularVelocity = Vector3.zero
			end
		end

		tbl4.EndFlight = function()
			tbl4.Flying = false
			local sliced14 = tbl4.Root()

			if sliced14 then
				pcall(function()
					sliced14.AssemblyLinearVelocity = Vector3.zero
					sliced14.AssemblyAngularVelocity = Vector3.zero
				end)
			end

			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid then
				humanoid.PlatformStand = false
			end
		end

		do
			local tbl11 = {
				Enum.HumanoidStateType.FallingDown,
				Enum.HumanoidStateType.Ragdoll,
				Enum.HumanoidStateType.Physics,
				Enum.HumanoidStateType.Seated,
				Enum.HumanoidStateType.PlatformStanding,
			}

			local tbl12 = {}
			local flag = false

			tbl4.GodMode = function(arg)
				local character = localPlayer.Character
				local humanoid = character and character:FindFirstChildOfClass("Humanoid")
				if not character or not humanoid then
					return
				end

				if arg then
					flag = true

					for _, sliced14 in ipairs(tbl11) do
						pcall(function()
							humanoid:SetStateEnabled(sliced14, false)
						end)
					end

					pcall(function()
						humanoid.BreakJointsOnDeath = false
					end)

					for _, descendant in ipairs(character:GetDescendants()) do
						if descendant:IsA("BasePart") and tbl12[descendant] == nil then
							tbl12[descendant] = descendant.CanCollide

							pcall(function()
								descendant.CanCollide = false
							end)
						end
					end
				elseif flag then
					flag = false

					for _, sliced14 in ipairs(tbl11) do
						pcall(function()
							humanoid:SetStateEnabled(sliced14, true)
						end)
					end

					for k, sliced14 in pairs(tbl12) do
						if k and k.Parent then
							pcall(function()
								k.CanCollide = sliced14
							end)
						end
					end

					table.clear(tbl12)
				end
			end
		end

		tbl4.GodTick = function()
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid and humanoid.Health < humanoid.MaxHealth then
				pcall(function()
					humanoid.Health = humanoid.MaxHealth
				end)
			end
		end

		tbl4.StopWalking = function()
			local character = localPlayer.Character
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid and humanoidRootPart then
				pcall(function()
					humanoid:MoveTo(humanoidRootPart.Position)
					humanoid:Move(Vector3.zero, false)
				end)
			end
		end

		local function slicedfn11(arg, arg2, arg3, arg4)
			local n = tonumber(arg2) or 6
			local slicedn2 = tonumber(arg3) or 10
			local slicedn3 = 0
			local flag = nil
			local slicedn4 = 0
			local slicedn5 = 0

			while slicedn3 < slicedn2 do
				if type(arg4) == "function" and arg4() then
					tbl4.StopWalking()
					return false
				end
				local character = localPlayer.Character
				local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
				character = character and character:FindFirstChildOfClass("Humanoid")
				if not humanoidRootPart or not character or character.Health <= 0 then
					return false
				end

				if (humanoidRootPart.Position - arg).Magnitude <= n then
					tbl4.StopWalking()
					return true
				end
				flag = flag and (humanoidRootPart.Position - flag).Magnitude < 1

				if flag then
					slicedn4 += 0.2
				else
					slicedn4 = 0
				end

				flag = humanoidRootPart.Position
				slicedn5 = math.max(0, slicedn5 - 0.2)

				if slicedn4 >= 0.8 and slicedn5 <= 0 then
					tbl4.LeaveBelt()

					pcall(function()
						character.Jump = true
					end)

					slicedn4 = 0
					slicedn5 = 1.5
				end

				character:MoveTo(arg)
				slicedn3 += task.wait(0.2)
			end

			tbl4.StopWalking()
			return tbl4.DistanceTo(arg) <= n
		end

		tbl4.WalkTo = function(arg, arg2, arg3, arg4)
			tbl4.Driving = tbl4.Driving + 1
			local ok, result = pcall(slicedfn11, arg, arg2, arg3, arg4)
			tbl4.Driving = math.max(0, tbl4.Driving - 1)
			return ok and result == true
		end

		local tbl11 = {
			Boss = "Fractured",
			GreatBloom = "Spirit Bloom",
			Sakura = "Bloom",
			Monstrous = "Parasite",
		}

		task.spawn(function()
			local mutations = tbl.Mutations

			local ok, result = pcall(function()
				return mutations.All()
			end)

			if ok and type(result) == "table" then
				for k, sliced14 in pairs(result) do
					local id = type(sliced14) == "table" and (sliced14.Id or k) or nil
					local label = type(sliced14) == "table" and sliced14.Label or nil

					if id ~= nil and type(label) == "string" and label ~= "" then
						tbl11[tostring(id)] = label
					end
				end
			end
		end)

		slicedfn7 = function(arg)
			return tbl11[tostring(arg)] or tostring(arg)
		end

		local tbl12, n, tbl13, tbl14, tbl15, tbl16, flag, tbl17, slicedn2, slicedn3
		local slicedn4, slicedfn12

		do
			local tbl18 = {
				"Forest",
				"Desert",
				"Snow",
				"Lake",
				"Jungle",
				"Volcano",
				"Prehistoric",
				"Cosmic",
				"Abyss Ocean",
				"Cherry Blossom",
				"Light Dark",
				"Titan Temple",
				"Enchanted Forest",
			}

			local tbl19 = {}

			for _, sliced14 in ipairs(tbl18) do
				tbl19[sliced14] = true
			end

			task.spawn(function()
				local eggState = tbl.EggState

				local ok, result = pcall(function()
					return eggState.ReadFieldEggs()
				end)

				if ok and type(result) == "table" and type(result.Records) == "table" then
					for _, record in pairs(result.Records) do
						local areaId = type(record) == "table" and record.AreaId or nil

						if type(areaId) == "string" and not tbl19[areaId] then
							tbl19[areaId] = true
							table.insert(tbl18, areaId)
						end
					end
				end
			end)

			tbl8 = { "Any" }
			tbl9 = { Any = 0 }
			local tbl20 = {}
			local directory = tbl.Assets and tbl.Assets.Directory

			if type(directory) == "table" then
				for _, sliced14 in pairs(directory) do
					local rarity = type(sliced14) == "table" and sliced14.Rarity or nil
					local flag2 = type(rarity) == "table"

					if flag2 then
						flag2 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					local sliced15 = flag2 or nil

					if sliced15 then
						local str = tbl20[sliced15]

						if not str then
							str = tostring(rarity.DisplayName or rarity._id or sliced15)
						end

						tbl20[sliced15] = str
					end
				end
			end

			if next(tbl20) == nil then
				tbl20 = {
					"Common",
					"Uncommon",
					"Rare",
					"Epic",
					"Legendary",
					"Mythic",
					"Cosmic",
					"Secret",
					"Eternal",
					"Divine",
				}
			end

			local tbl21 = {}

			for k in pairs(tbl20) do
				table.insert(tbl21, k)
			end

			table.sort(tbl21)

			for _, sliced14 in ipairs(tbl21) do
				table.insert(tbl8, tbl20[sliced14])
				tbl9[tbl20[sliced14]] = sliced14
			end

			tbl5 = { "Best Rarity", "Biggest Weight", "Best Mutation", "Highest Value", "Lowest Value" }
			tbl12 = {}
			n = 0
			tbl13 = {}
			tbl14 = {}
			tbl15 = {}
			tbl16 = {}
			tbl4.Steal.RiftPriority = false
			tbl4.Steal.RiftNeeds = {}
			flag = false
			tbl17 = {}
			slicedn2 = 0
			sliced4 = tbl5[4]
			slicedn3 = 27.4
			slicedn4 = 400
			slicedfn12 = nil

			sliced5 = sliced8:CreateToggle({
				Name = "Auto Steal",
				Default = false,
				Callback = function()
					if slicedfn12 then
						slicedfn12()
					end
				end,
			})

			for _, sliced14 in ipairs(tbl18) do
				tbl12[sliced14] = true
			end

			slicedfn6(sliced8:CreateMultiDropdown({
				Name = "Target Areas",
				Options = tbl18,
				Default = tbl18,
				Callback = function(arg)
					local tbl22 = {}

					if type(arg) == "table" then
						for k, sliced14 in pairs(arg) do
							if sliced14 == true and type(k) == "string" then
								tbl22[k] = true
							elseif type(sliced14) == "string" then
								tbl22[sliced14] = true
							end
						end
					end

					if next(tbl22) == nil then
						for _, sliced14 in ipairs(tbl18) do
							tbl22[sliced14] = true
						end
					end

					tbl12 = tbl22
				end,
			}))
		end

		sliced8:CreateDropdown({
			Name = "Min Rarity",
			Note = "Steal eggs of the chosen rarity and every rarity above it",
			Options = tbl8,
			Default = tbl8[1],
			Callback = function(arg)
				n = tbl9[arg] or 0
			end,
		})

		slicedfn5(sliced8, {
			Name = "Min Steal Value",
			Note = "Skip eggs worth less than this. Drag or type 250k, 50m, 1.5b",
			Legacy = "Min Value To Steal",
			SectionName = "Auto Steal",
			OnRaw = function(arg)
				slicedn2 = arg
			end,
		})

		do
			local tbl18 = {}
			local tbl19 = {}
			local directory = tbl.Assets and tbl.Assets.Directory
			local tbl20 = {}

			if type(directory) == "table" then
				for k, sliced14 in pairs(directory) do
					local rarity = type(sliced14) == "table" and sliced14.Rarity or nil
					local rarity2 = type(rarity) == "table"

					if rarity2 then
						rarity2 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					rarity2 = rarity2 or nil

					if rarity2 then
						local insert = table.insert
						local tbl21 = { Category = tostring(k) }
						local tostring = tostring
						k = sliced14.DisplayName or k
						tbl21.Name = tostring(k)
						tbl21.Rarity = rarity2
						tbl21.RarityName = tostring(rarity.DisplayName or rarity._id or rarity2)
						insert(tbl20, tbl21)
					end
				end
			end

			table.sort(tbl20, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity > arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced14 in ipairs(tbl20) do
				local str = string.format("%s [%s]", sliced14.Name, sliced14.RarityName)

				if tbl19[str] then
					str = string.format("%s [%s] (%s)", sliced14.Name, sliced14.RarityName, sliced14.Category)
				end

				table.insert(tbl18, str)
				tbl19[str] = sliced14.Category
			end

			slicedfn6(sliced8:CreateMultiDropdown({
				Name = "Target Specific Eggs",
				Note = "Only steal these eggs (empty = all)",
				Options = tbl18,
				Default = {},
				Callback = function(arg)
					local tbl21 = {}

					if type(arg) == "table" then
						for k, sliced14 in pairs(arg) do
							k = sliced14 == true and type(k) == "string" and k

							if k then
								sliced14 = k
							else
								sliced14 = type(sliced14) == "string" and sliced14
							end

							sliced14 = sliced14 or nil

							if sliced14 and tbl19[sliced14] then
								tbl21[tbl19[sliced14]] = true
							end
						end
					end

					tbl13 = tbl21
				end,
			}))
		end

		do
			local slicedn5 = 30
			local sliced14 = nil
			local flag2 = false
			local slicedn6 = 0

			local function slicedfn13()
				local tbl18 = {}
				local save2 = tbl.Save

				if type(save2) == "table" and type(save2.Get) == "function" then
					local ok, result = pcall(save2.Get)

					if ok and type(result) == "table" then
						local pairs = pairs
						local inventory = result.Inventory or {}

						for _, sliced16 in pairs(inventory) do
							if type(sliced16) == "table" and sliced16.Category ~= nil then
								tbl18[tostring(sliced16.Category)] = true
							end
						end

						local sliced16 = pairs
						local eggInventory = result.EggInventory or {}

						for _, sliced17 in sliced16(eggInventory) do
							if type(sliced17) == "table" and sliced17.AssetCategory ~= nil then
								tbl18[tostring(sliced17.AssetCategory)] = true
							end
						end
					end
				end

				return tbl18
			end

			local function slicedfn14()
				local rfScrambleTradeInAskState = networking:FindFirstChild("RF/ScrambleTradeIn/AskState")
				if not rfScrambleTradeInAskState or not rfScrambleTradeInAskState:IsA("RemoteFunction") then
					return
				end
				local ok, result = pcall(rfScrambleTradeInAskState.InvokeServer, rfScrambleTradeInAskState)
				if not ok or type(result) ~= "table" or type(result.Requirements) ~= "table" then
					return
				end
				local sliced15 = slicedfn13()
				local riftNeeds = {}

				for _, requirement in pairs(result.Requirements) do
					if not sliced15[tostring(requirement)] then
						riftNeeds[tostring(requirement)] = true
					end
				end

				tbl4.Steal.RiftNeeds = riftNeeds
			end

			tbl3.Add(function()
				if not tbl4.Steal.RiftPriority or flag2 or os.clock() < slicedn6 then
					return false
				end
				flag2 = true
				slicedn6 = os.clock() + slicedn5

				task.spawn(function()
					pcall(slicedfn14)
					flag2 = false
				end)

				return false
			end)

			local function slicedfn15()
				local riftNeeds = tbl4.Steal.RiftNeeds
				if not tbl4.Steal.RiftPriority or next(riftNeeds) == nil then
					return
				end
				local sliced15 = slicedfn13()
				local flag3 = false

				for k in pairs(riftNeeds) do
					if sliced15[k] then
						riftNeeds[k] = nil
						flag3 = true
					end
				end

				if flag3 then
					tbl3.Wake()
				end
			end

			local save2 = tbl.Save

			if type(save2) == "table" and type(save2.FieldSignal) == "function" then
				for _, sliced15 in ipairs({ "EggInventory", "Inventory" }) do
					local ok, result = pcall(save2.FieldSignal, sliced15)

					if ok and type(result) == "table" and type(result.Connect) == "function" then
						local ok2, result2 = pcall(result.Connect, result, function()
							task.defer(slicedfn15)
						end)

						if ok2 and result2 then
							slicedfn4(function()
								pcall(function()
									result2:Disconnect()
								end)
							end)
						end
					end
				end
			end

			sliced14 = sliced8:CreateToggle({
				Name = "Steal Missing Lab Eggs",
				Default = false,
				Callback = function()
					tbl4.Steal.RiftPriority = tbl4.Toggle(sliced14, false) == true
					slicedn6 = 0

					if not tbl4.Steal.RiftPriority then
						tbl4.Steal.RiftNeeds = {}
					end

					tbl3.Wake()
				end,
			})
		end

		do
			local slicedn5 = 5
			local slicedn6 = 5
			local slicedn7 = 60
			local sliced14 = nil
			local slicedn8 = 0
			local slicedn9 = 0
			local flag2 = false
			local tbl18 = {}

			local function slicedfn13()
				local save2 = tbl.Save

				if type(save2) == "table" and type(save2.Get) == "function" then
					local ok, result = pcall(save2.Get)
					if ok and type(result) == "table" then
						return result
					end
				end

				return nil
			end

			local function slicedfn14()
				local sliced15 = slicedfn13()
				local directory = tbl.Areas and tbl.Areas.Directory
				local directory2 = tbl.Assets and tbl.Assets.Directory
				if not sliced15 or type(directory) ~= "table" or type(directory2) ~= "table" then
					return
				end
				local index = type(sliced15.Index) == "table" and sliced15.Index or {}
				local tbl19 = {}
				local pairs = pairs
				local inventory = sliced15.Inventory or {}

				for _, sliced17 in pairs(inventory) do
					if type(sliced17) == "table" and sliced17.Category ~= nil then
						tbl19[tostring(sliced17.Category)] = true
					end
				end

				local sliced17 = pairs
				local eggInventory = sliced15.EggInventory or {}

				for _, sliced18 in sliced17(eggInventory) do
					if type(sliced18) == "table" and sliced18.AssetCategory ~= nil then
						tbl19[tostring(sliced18.AssetCategory)] = true
					end
				end

				local tbl20 = {}

				for _, sliced18 in pairs(directory) do
					local flag3 = type(sliced18) == "table" and type(sliced18.Rarity) == "table"

					if flag3 then
						flag3 = tonumber(sliced18.Rarity.RarityNumber or sliced18.Rarity.Rank)
					end

					flag3 = flag3 or 0
					local sliced19 = pairs
					local dropTable = type(sliced18) == "table" and sliced18.DropTable or {}

					for _, sliced20 in sliced19(dropTable) do
						local flag4 = type(sliced20) == "table" and sliced20[1] or nil
						local slicedn10 = type(sliced20) == "table" and tonumber(sliced20[2]) or 0
						local flag5 = flag4 ~= nil and directory2[flag4] or nil

						if type(flag5) == "table" and slicedn10 > 0 and flag5.DontRoll ~= true then
							local str = tostring(flag4)

							if index[flag4] ~= true and not tbl19[str] and (tbl20[str] == nil or flag3 > tbl20[str]) then
								tbl20[str] = flag3
							end
						end
					end
				end

				tbl17 = tbl20
			end

			local function slicedfn15(arg, ...)
				local sliced15 = networking:FindFirstChild(arg)
				if not sliced15 or not sliced15:IsA("RemoteFunction") then
					return false
				end
				local ok, result = pcall(sliced15.InvokeServer, sliced15, ...)
				return ok and result ~= false
			end

			local function slicedfn16(arg, arg2)
				local tbl19 = {}
				if type(arg) ~= "table" then
					return tbl19
				end

				for _, sliced15 in ipairs(arg2) do
					local flag3 = arg

					for _, sliced16 in ipairs(sliced15) do
						flag3 = type(flag3) == "table" and flag3[sliced16] or nil
					end

					local ipairs = ipairs
					local tbl20 = type(flag3) == "table" and flag3 or {}

					for _, sliced17 in ipairs(tbl20) do
						if type(sliced17) == "table" and sliced17.AssetId ~= nil then
							table.insert(tbl19, sliced17.AssetId)
						end
					end
				end

				return tbl19
			end

			local tbl19 = {
				{
					Id = "LimitedEgg",
					Gear = "GravityDisruptor",
					Module = "LimitedEgg",
					Lists = { { "Entries" }, { "MechaReroll", "Entries" } },
				},
				{
					Id = "BrainrotEgg",
					Gear = "BeeLauncher",
					Module = "BrainrotEgg",
					Lists = { { "Entries" } },
				},
				{
					Id = "MonsterEgg",
					Gear = "BeeLauncher",
					Module = "MonsterEgg",
					Lists = { { "Entries" }, { "MechaEntries" } },
				},
			}

			local function slicedfn17()
				local sliced15 = slicedfn13()
				if not sliced15 then
					return
				end
				local index = type(sliced15.Index) == "table" and sliced15.Index or {}
				local indexClaimedCategories = type(sliced15.IndexClaimedCategories) == "table" and sliced15.IndexClaimedCategories or {}

				for k, sliced16 in pairs(index) do
					if sliced16 == true and indexClaimedCategories[k] ~= true then
						slicedfn15("RF/Codex/AskRedeemAll")
						break
					end
				end

				local gearInventory = type(sliced15.GearInventory) == "table" and sliced15.GearInventory or {}

				for _, sliced16 in ipairs(tbl19) do
					local flag3 = (tonumber(gearInventory[sliced16.Gear]) or 0) <= 0

					if flag3 then
						flag3 = os.clock() >= (tbl18[sliced16.Id] or 0)
					end

					if flag3 then
						local sliced17 = slicedfn16(tbl[sliced16.Module], sliced16.Lists)
						local flag4 = #sliced17 > 0

						for _, sliced18 in ipairs(sliced17) do
							if index[sliced18] ~= true then
								flag4 = false
								break
							end
						end

						if flag4 then
							tbl18[sliced16.Id] = os.clock() + slicedn7
							slicedfn15("RF/Codex/AskRedeemLimitedEgg", sliced16.Id)
						end
					end
				end
			end

			tbl3.Add(function()
				local now = os.clock()

				if flag and now >= slicedn8 then
					slicedn8 = now + slicedn5
					pcall(slicedfn14)
				end

				if not flag2 and now >= slicedn9 and tbl4.Toggle(tbl4.IndexClaimHandle, false) then
					flag2 = true
					slicedn9 = now + slicedn6

					task.spawn(function()
						pcall(slicedfn17)
						flag2 = false
					end)
				end

				return false
			end)

			sliced14 = sliced8:CreateToggle({
				Name = "Steal Missing Index Eggs",
				Note = "Also steal eggs missing from your index, highest area first",
				Default = false,
				Callback = function()
					flag = tbl4.Toggle(sliced14, false) == true
					slicedn8 = 0

					if not flag then
						tbl17 = {}
					end

					tbl3.Wake()
				end,
			})

			tbl4.IndexClaimRestart = function()
				slicedn9 = 0
				tbl3.Wake()
			end
		end

		tbl4.Steal.PriorityHandle = sliced8:CreateDropdown({
			Name = "Steal Priority",
			Options = tbl5,
			Default = tbl5[4],
			Callback = function(arg)
				if table.find(tbl5, arg) then
					sliced4 = arg

					if type(tbl4.ResortSteal) == "function" then
						tbl4.ResortSteal()
					end
				end
			end,
		})

		tbl4.SafeCarry.RunHandle = sliced8:CreateSlider({
			Name = "Tween Speed",
			Note = "Over 100% may glitch",
			Min = 50,
			Max = 115,
			Default = 100,
			Increment = 1,
			Unit = "%",
			Callback = function(arg)
				tbl4.SafeCarry.RunSpeed = math.clamp(tonumber(arg) or 100, 50, 115) / 100
			end,
		})

		tbl4.SafeCarry.CarryHandle = sliced8:CreateSlider({
			Name = "Carry Speed",
			Min = 80,
			Max = 115,
			Default = 100,
			Increment = 1,
			Unit = "%",
			Callback = function(arg)
				tbl4.SafeCarry.CarryScale = math.clamp(tonumber(arg) or 100, 80, 115) / 100
			end,
		})

		tbl4.SafeCarry.StopsHandle = sliced8:CreateSlider({
			Name = "Delivery Steps",
			Note = "Delivery Stop: stops on the way home. 3 is recommended; fewer steps is possible but the chance it works drops (1 = no stop)",
			Min = 1,
			Max = 6,
			Default = 3,
			Increment = 1,
			Callback = function(arg)
				local previous = tbl4.SafeCarry.Stops or 3
				local v = math.clamp(math.floor(tonumber(arg) or 3), 1, 6)
				tbl4.SafeCarry.Stops = v

				if v <= 2 and v < previous and SourcesLib.ParticlesOn and SourcesLib.RiskBadge then
					SourcesLib.RiskBadge("DELIVERY STEPS: " .. v .. " - RISKY",
						"Fewer stops is faster, but the server can reject the delivery, pull you back, or the guard can send the egg back to its nest. 3 is the safe value.", 10)
				end
			end,
		})

		-- three delivery modes. The mode is the only switch for the hops: Instant TP hops home the moment the egg is
		-- in hand, Delivery Stop does the same with stops on the way, Normal walks (Anti Guard is its own option).
		-- Go Method: how the character reaches the egg (Fly = the hub's tween above the ground, Run = on the ground)
		tbl4.GoMethod = {
			Names = { "Run", "Fly" },
			Current = function()
				return tbl4.SafeCarry.GoMethod or "Fly"
			end,
			Apply = function(name)
				local sc = tbl4.SafeCarry

				if not table.find(tbl4.GoMethod.Names, name) then
					name = "Fly"
				end
				sc.GoMethod = name
				sc.RunHeight = name == "Fly" and 50 or 0
				local handle = sc.GoHandle

				if handle and type(handle.Set) == "function" then
					pcall(handle.Set, handle, name, false)
				end
			end,
		}

		-- one speed ceiling for the whole delivery, in every mode: 115% (hop distance is not a speed and keeps its own ratio)
		tbl4.SafeCarry.Cap = function(ratio)
			return math.min(ratio, 1.15)
		end

		tbl4.NoticeLib = SourcesLib

		tbl4.Method = {
			Names = { "Normal", "Instant TP", "Delivery Stop" },
			Current = function()
				local sc = tbl4.SafeCarry

				if sc.Teleport then
					return "Instant TP"
				end

				if sc.LineDrop then
					return "Delivery Stop"
				end
				return "Normal"
			end,
			Apply = function(name)
				local sc = tbl4.SafeCarry
				local ag = tbl4.AntiGuard

				if not table.find(tbl4.Method.Names, name) then
					name = "Normal"
				end

				tbl4.MethodApplying = true
				sc.Teleport = name == "Instant TP"
				sc.StopMode = name == "Delivery Stop"
				sc.LineDrop = name ~= "Normal"
				sc.HopStop = name == "Instant TP" and 14 or 48
				sc.SnapPickup = false

				if name == "Instant TP" and tbl4.GoMethod.Current() == "Fly" then
					tbl4.GoMethod.Apply("Run")
				end
				sc.SpeedJitter = sc.LineDrop and 0 or 0.08

				if name == "Delivery Stop" or name == "Instant TP" then
					local handle = ag.Handle

					if handle and type(handle.Set) == "function" then
						pcall(handle.Set, handle, false)
					end
					ag.Enabled = false
				end

				local methodHandle = sc.MethodHandle

				if methodHandle and type(methodHandle.Set) == "function" then
					pcall(methodHandle.Set, methodHandle, name, false)
				end
				tbl4.MethodApplying = false

				if name ~= "Normal" and SourcesLib and SourcesLib.Banner then
					SourcesLib.Banner(name .. ": max 115%, faster = bug", 5)
				end

				if ag.Render and tbl4.UiDefer then
					tbl4.UiDefer(function()
						pcall(ag.Render, false)
					end)
				end

				if tbl4.StealPanelSync then
					pcall(tbl4.StealPanelSync)
				end
			end,
		}

		SourcesLib.TripStatus = function()
			local now = os.clock()
			local sc = tbl4.SafeCarry

			if sc.LastFailed and now - sc.LastFailed < 3 and sc.LastFailed > (sc.LastDelivered or 0) then
				return 1, "fail"
			end

			if sc.LastDelivered and now - sc.LastDelivered < 2 then
				return 1, "done"
			end
			local trip = tbl4.Trip

			if trip and now - (trip.At or 0) < 1.5 then
				return trip.Progress or 0, "run"
			end

			if tbl4.Steal.Carrying then
				return 0.03, "run"
			end
			return nil
		end

		tbl4.SafeCarry.TpFpsCap = true
		tbl4.SafeCarry.TpFpsHandle = sliced8:CreateToggle({
			Name = "Instant TP FPS Cap (60 / 30)",
			Note = "Instant TP: the FPS cap flips between 60 and 30 from the start of the steal until it is over",
			Default = true,
			Callback = function(arg)
				if type(arg) ~= "boolean" then
					arg = tbl4.Toggle(tbl4.SafeCarry.TpFpsHandle, true)
				end
				tbl4.SafeCarry.TpFpsCap = arg == true

				if not tbl4.SafeCarry.TpFpsCap then
					pcall(tbl4.CarryCap.Off)
				end
			end,
		})

		tbl4.SafeCarry.GoHandle = sliced8:CreateDropdown({
			Name = "Go Method",
			Note = "How you reach the egg: Run (on the ground) or Fly (above the ground)",
			Options = tbl4.GoMethod.Names,
			Default = "Fly",
			Callback = function(arg)
				if table.find(tbl4.GoMethod.Names, arg) and tbl4.GoMethod.Current() ~= arg then
					tbl4.GoMethod.Apply(arg)
				end
			end,
		})

		tbl4.SafeCarry.PortalRoute = true
		tbl4.SafeCarry.PortalHandle = sliced8:CreateToggle({
			Name = "Semi TP",
			Note = "Fly: TP into the Light Dark biome through the portal, come back out, then fly the rest at 110%",
			Default = true,
			Callback = function(arg)
				if type(arg) ~= "boolean" then
					arg = tbl4.Toggle(tbl4.SafeCarry.PortalHandle, true)
				end
				tbl4.SafeCarry.PortalRoute = arg == true
			end,
		})

		tbl4.SafeCarry.MethodHandle = sliced8:CreateDropdown({
			Name = "Delivery Method",
			Note = "Normal (walk) / Instant TP (the hub's Instant Steal method: hops home, egg put down at the line and taken back) / Delivery Stop (hops with stops)",
			Options = tbl4.Method.Names,
			Default = "Delivery Stop",
			Callback = function(arg)
				if tbl4.MethodReady and table.find(tbl4.Method.Names, arg) and tbl4.Method.Current() ~= arg then
					tbl4.Method.Apply(arg)
				end
			end,
		})

		-- clone left where the egg was taken (client side, removed when the delivery ends)
		tbl4.PostClone = function()
			tbl4.DropClone()
			local character = localPlayer.Character
			if not character then
				return
			end
			local was = character.Archivable
			character.Archivable = true
			local copy = character:Clone()
			character.Archivable = was

			if copy then
				for _, d in ipairs(copy:GetDescendants()) do
					if d:IsA("LuaSourceContainer") or d:IsA("Humanoid") then
						pcall(function()
							d:Destroy()
						end)
					elseif d:IsA("BasePart") then
						d.Anchored = true
						d.CanCollide = false
						d.CanTouch = false
						d.CanQuery = false
					end
				end

				copy.Name = "Clone"
				copy.Parent = workspace
				tbl4.StealClone = copy
			end
		end

		-- removes every client-side copy of the player (Anti Guard's copy and the one left at the egg)
		tbl4.ClearClones = function()
			if SourcesLib.ReleaseCamera then
				pcall(SourcesLib.ReleaseCamera)
			end
			pcall(tbl4.DropClone)
		end

		tbl4.DropClone = function()
			local copy = tbl4.StealClone
			tbl4.StealClone = nil

			if copy then
				pcall(function()
					copy:Destroy()
				end)
			end
		end

		-- FPS dip while the delivery is running (restores the FPS Cap slider value afterwards)
		tbl4.SafeCarry.CarryFps = 35
		tbl4.CarryCap = {
			Active = false,
			On = function(fps)
				local cap = tbl4.CarryCap
				if cap.Active or type(setfpscap) ~= "function" then
					return
				end
				cap.Active = true
				cap.At = os.clock()
				if fps == "pulse" then
					-- 60 / 30 FPS battle: the cap keeps flipping between the two values while it is on
					cap.Gen = (cap.Gen or 0) + 1
					local mine = cap.Gen

					task.spawn(function()
						local high = true

						while cap.Active and cap.Gen == mine do
							pcall(setfpscap, high and 60 or 30)
							high = not high
							task.wait(0.15)
						end
					end)
				else
					pcall(setfpscap, math.clamp(math.floor(tonumber(fps) or tonumber(tbl4.SafeCarry.CarryFps) or 35), 5, 240))
				end
				task.delay(60, function()
					if cap.Active and os.clock() - cap.At >= 59 then
						cap.Off()
					end
				end)
			end,
			Off = function()
				local cap = tbl4.CarryCap
				if not cap.Active then
					return
				end
				cap.Active = false
				local normal = 240
				local handle = tbl4.FpsCapHandle

				if handle and type(handle.Get) == "function" then
					local ok, value = pcall(handle.Get, handle)
					normal = ok and tonumber(value) or 240
				end

				if type(setfpscap) == "function" then
					pcall(setfpscap, math.clamp(math.floor(normal), 5, 1000))
				end
			end,
		}

		
		-- screen-aware default: 35 FPS on a 60 FPS screen, 70 on 120, and so on (only while the slider is untouched)
		SourcesLib.OnRefFps = function(ref)
			local sc = tbl4.SafeCarry

			if sc.CarryFpsUser then
				return
			end
			local v = math.clamp(math.floor(ref * 35 / 60 + 0.5), 5, 240)
			sc.CarryFps = v
			local handle = sc.CarryFpsHandle

			if handle and type(handle.Set) == "function" then
				pcall(handle.Set, handle, v, false)
			end
		end

		-- ===== analyzer: records every delivery and copies a report to the clipboard =====
		do
			local A = {
				Enabled = false,
				Detail = 2,
				Active = false,
				Events = {},
				Meta = {},
				T0 = 0,
				RelocateAt = 0,
				ImpulseAt = 0,
				Last = nil,
				Run = 0,
			}
			tbl4.Analyzer = A

			local function ser(v, depth)
				depth = depth or 0
				local t = typeof(v)

				if t == "number" then
					return tostring(math.floor(v * 1000 + 0.5) / 1000)
				elseif t == "string" then
					return '"' .. (#v > (A.Detail >= 3 and 200 or 48) and (string.sub(v, 1, A.Detail >= 3 and 200 or 48) .. '~') or v) .. '"'
				elseif t == "boolean" or t == "nil" then
					return tostring(v)
				elseif t == "Vector2" then
					return string.format("(%.2f, %.2f)", v.X, v.Y)
				elseif t == "Vector3" then
					return string.format("(%.1f, %.1f, %.1f)", v.X, v.Y, v.Z)
				elseif t == "CFrame" then
					local p = v.Position
					return string.format("CF(%.1f, %.1f, %.1f)", p.X, p.Y, p.Z)
				elseif t == "Instance" then
					return v.ClassName .. ":" .. v.Name
				elseif t == "table" then
					if depth >= (A.Detail >= 2 and 2 or 1) then
						return "{...}"
					end
					local parts, n = {}, 0

					for k, val in pairs(v) do
						n += 1

						if n > (A.Detail == 1 and 8 or (A.Detail == 2 and 16 or 30)) then
							parts[#parts + 1] = "..."
							break
						end
						parts[#parts + 1] = tostring(k) .. "=" .. ser(val, depth + 1)
					end

					table.sort(parts)
					return "{" .. table.concat(parts, ", ") .. "}"
				end
				return t
			end
			A.Ser = ser

			-- guards can live in several containers: look in all of them
			A.GuardObjects = function()
				local list = {}
				local seen = {}

				local function consider(inst)
					if seen[inst] then
						return
					end

					if inst:IsA("Model") then
						local lower = string.lower(inst.Name)

						if inst:GetAttribute("GuardState") ~= nil or string.find(lower, "guard", 1, true) or string.find(lower, "sentry", 1, true) then
							seen[inst] = true
							list[#list + 1] = inst
						end
					end
				end

				for _, child in ipairs(workspace:GetChildren()) do
					consider(child)

					if child:IsA("Folder") then
						for _, inner in ipairs(child:GetChildren()) do
							consider(inner)
						end
					end
				end

				local world = workspace:FindFirstChild("World")

				if world then
					for _, name in ipairs({ "Sentries", "Guards" }) do
						local folder = world:FindFirstChild(name)

						if folder then
							for _, inner in ipairs(folder:GetDescendants()) do
								consider(inner)
							end
						end
					end
				end

				return list
			end

			A.Island = function()
				local area = tbl4.Steal.CarryAreaId

				if type(area) ~= "string" or area == "" then
					area = localPlayer:GetAttribute("AreaId")
				end
				return type(area) == "string" and area ~= "" and area or "unknown"
			end

			A.Event = function(name, data)
				if not A.Active or #A.Events >= (A.Detail == 1 and 120 or (A.Detail == 2 and 300 or 600)) then
					return
				end
				A.Events[#A.Events + 1] = string.format("[%6.2f] %s %s", os.clock() - A.T0, name, data ~= nil and ser(data) or "")
			end

			local function copy(text)
				local fn = setclipboard or toclipboard
				if type(fn) == "function" then
					return pcall(fn, text)
				end
				return false
			end
			A.Copy = copy

			A.Begin = function(method, ladder)
				A.Run += 1
				local run = A.Run
				A.Active = true
				A.T0 = os.clock()
				A.Events = {}
				local root = tbl4.Root()
				local home = nil

				if type(tbl4.StealHome) == "function" then
					local ok, value = pcall(tbl4.StealHome)
					home = ok and value or nil
				end

				local sc = tbl4.SafeCarry
				local meta = {}
				meta[#meta + 1] = os.date("%H:%M:%S") .. " place " .. tostring(game.PlaceId) .. (A.Detail >= 2 and (" job " .. tostring(game.JobId)) or "")
				local exName = "?"

				if typeof(identifyexecutor) == "function" then
					local okExec, nameExec = pcall(identifyexecutor)
					exName = okExec and tostring(nameExec) or "?"
				end

				meta[#meta + 1] = "exec: " .. exName
				meta[#meta + 1] = "island: " .. A.Island() .. " / me: " .. tostring(localPlayer:GetAttribute("AreaId"))
				meta[#meta + 1] = "egg: " .. tostring(sc.Category) .. " x" .. tostring(sc.Mult)
				meta[#meta + 1] = "method: " .. tostring(method) .. " " .. table.concat(ladder or {}, ">")
				meta[#meta + 1] = string.format("ws %s root %s home %s", tostring(tbl4.WalkSpeed()), root and ser(root.Position) or "?", home and ser(home) or "?")

				if root and home then
					meta[#meta + 1] = string.format("dist %.0f", (root.Position - home).Magnitude)
				end

				local line = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				line = line and line:FindFirstChild("Areas")
				line = line and line:FindFirstChild("SeparationLine")
				meta[#meta + 1] = "line: " .. (line and line:IsA("BasePart") and ser(line.Position) or "none")
				meta[#meta + 1] = "AG: " .. tostring(tbl4.AntiGuard.Enabled) .. " " .. tostring(type(tbl4.AntiGuard.ProfileName) == "function" and select(2, pcall(tbl4.AntiGuard.ProfileName)) or "?")
				local guards = tbl.Guards
				local entry = type(guards) == "table" and type(guards.Directory) == "table" and guards.Directory[tostring(tbl4.Steal.CarryAreaId)] or nil
				meta[#meta + 1] = A.Detail >= 2 and ("guard: " .. ser(entry)) or ("guard ws: " .. tostring(type(entry) == "table" and entry.WalkSpeed or "?"))

				local keys = { "LineDrop", "StopMode", "Stops", "Hops", "HopRatio", "HopGap", "HopLift", "DirectBudget", "DirectMargin", "LineWait", "CarryRatio", "Height" }
				local cfg = {}

				if A.Detail >= 3 then
					for k, v in pairs(sc) do
						local t = type(v)

						if t == "number" or t == "boolean" or t == "string" then
							cfg[#cfg + 1] = tostring(k) .. "=" .. ser(v)
						end
					end

					table.sort(cfg)
				else
					if A.Detail == 2 then
						for _, k in ipairs({ "StopTime", "FarFromLine", "CrossRatio", "CrossSpeed", "PickupSpeed", "HopStep", "HopStop", "DropDelay", "LineApproach", "ReJump", "RunSpeed", "CarryScale", "CarryFps" }) do
							keys[#keys + 1] = k
						end
					end

					for _, k in ipairs(keys) do
						cfg[#cfg + 1] = k .. "=" .. ser(sc[k])
					end
				end

				meta[#meta + 1] = "cfg: " .. table.concat(cfg, " ")
				A.Meta = meta
				A.Event("begin", method)

				task.spawn(function()
					local last = 0

					while A.Active and A.Run == run do
						task.wait(A.Detail == 1 and 1 or (A.Detail == 2 and 0.5 or 0.25))
						local r = tbl4.Root()
						local humanoid = localPlayer.Character and localPlayer.Character:FindFirstChildOfClass("Humanoid")

						if r then
							local ping = 0
							pcall(function()
								ping = game:GetService("Stats").Network.ServerStatsItem["Data Ping"]:GetValue()
							end)
							A.Event("pos", string.format("%s v%.0f %s c=%s ag=%s %dms", ser(r.Position), r.AssemblyLinearVelocity.Magnitude, humanoid and string.gsub(tostring(humanoid:GetState()), "Enum.HumanoidStateType.", "") or "?", tostring(tbl4.Steal.Carrying), tostring(tbl4.AntiGuard.Busy), ping))
						end

						if os.clock() - last >= (A.Detail == 1 and 2 or 1) and r then
							last = os.clock()
							local found = {}

							for _, child in ipairs(A.GuardObjects()) do
								found[#found + 1] = { Name = child.Name, State = child:GetAttribute("GuardState") or "?", Dist = (child:GetPivot().Position - r.Position).Magnitude }
							end

							table.sort(found, function(x, y)
								return x.Dist < y.Dist
							end)

							local limit = A.Detail == 1 and 1 or (A.Detail == 2 and 3 or 8)

							for gi = 1, math.min(limit, #found) do
								local g = found[gi]
								A.Event("guard", string.format("%s %s %.0f", g.Name, tostring(g.State), g.Dist))
							end
						end
					end
				end)
			end

			A.Record = function(island, level, ok)
				tbl4.MethodStats = tbl4.MethodStats or {}
				local byIsland = tbl4.MethodStats[island]

				if not byIsland then
					byIsland = {}
					tbl4.MethodStats[island] = byIsland
				end

				local s = byIsland[level]

				if not s then
					s = { Ok = 0, Fail = 0, Streak = 0, At = 0 }
					byIsland[level] = s
				end

				if ok then
					s.Ok += 1
					s.Streak = 0
				else
					s.Fail += 1
					s.Streak += 1
					s.At = os.clock()
				end
			end

			A.Finish = function(ok, reason)
				if not A.Active then
					return
				end
				A.Event("end", { ok = ok, reason = reason })
				A.Active = false
				local out = { "Sources Hub report: " .. (ok and "DELIVERED" or "FAILED") .. " (" .. tostring(reason) .. ") " .. string.format("%.1fs", os.clock() - A.T0) }

				for _, line in ipairs(A.Meta) do
					out[#out + 1] = line
				end

				out[#out + 1] = "--"

				for _, line in ipairs(A.Events) do
					out[#out + 1] = line
				end

				local parts = {}

				for island, levels in pairs(tbl4.MethodStats or {}) do
					for level, s in pairs(levels) do
						parts[#parts + 1] = string.format("%s/%s %d-%d", island, level, s.Ok, s.Fail)
					end
				end

				out[#out + 1] = "stats: " .. (#parts > 0 and table.concat(parts, ", ") or "-")
				local text = table.concat(out, "\n")

				local cap = A.Detail == 1 and 3200 or (A.Detail == 2 and 8000 or 24000)

				if #text > cap then
					text = string.sub(text, 1, math.floor(cap * 0.35)) .. "\n...\n" .. string.sub(text, -math.floor(cap * 0.62))
				end

				A.Last = text

				local tl = table.concat(A.Events, "\n")

				if #tl > 3400 then
					tl = "...\n" .. string.sub(tl, -3400)
				end

				A.LastTimeline = string.format("[timeline] %s (%s)\n%s", ok and "DELIVERED" or "FAILED", tostring(reason), tl)
				A.SetQueue(text, "report")

				if A.Enabled then
					A.CopyNext("report")
				end
			end

			-- reports are sent in 4 parts: each press copies the next one and says which it is
			-- two separate queues: the delivery report and the game scan never overwrite each other
			A.Queues = { report = { Parts = {}, Next = 1, N = 4 }, scan = { Parts = {}, Next = 1, N = 5 } }

			A.SetQueue = function(text, which, forcedParts)
				local q = A.Queues[which or "report"]

				if which == "scan" then
					q.N = forcedParts or 5
				end
				-- plain ASCII only (a cut in the middle of a multi-byte character makes setclipboard fail),
				-- parts are cut on line boundaries
				text = string.gsub(text, "[^\n\32-\126]", "?")
				local target = math.max(1, math.ceil(#text / q.N))
				q.Parts = {}
				local current = {}
				local size = 0

				for line in string.gmatch(text .. "\n", "([^\n]*)\n") do
					while #line > target * 2 do
						current[#current + 1] = string.sub(line, 1, target)
						line = string.sub(line, target + 1)
						q.Parts[#q.Parts + 1] = table.concat(current, "\n")
						current = {}
						size = 0
					end

					current[#current + 1] = line
					size += #line + 1

					if size >= target and #q.Parts < q.N - 1 then
						q.Parts[#q.Parts + 1] = table.concat(current, "\n")
						current = {}
						size = 0
					end
				end

				q.Parts[#q.Parts + 1] = table.concat(current, "\n")

				while #q.Parts < q.N do
					q.Parts[#q.Parts + 1] = "(end)"
				end

				while #q.Parts > q.N do
					q.Parts[q.N] = q.Parts[q.N] .. "\n" .. table.remove(q.Parts)
				end

				q.Next = 1
			end

			A.CopyNext = function(which)
				which = which or "report"
				local q = A.Queues[which]
				local label = which == "scan" and "scan" or "report"

				if #q.Parts == 0 then
					pcall(tbl4.Notify, "Analyzer", "No " .. label .. " yet")
					return false
				end

				if q.Next > q.N then
					q.Next = 1
				end

				local k = q.Next
				local ok = copy(string.format("[%s %d/%d]\n%s", label, k, q.N, q.Parts[k]))

				if not ok then
					pcall(tbl4.Notify, "Analyzer", string.format("%s part %d/%d: copy FAILED, press again", label, k, q.N))
					return false
				end

				q.Next = k + 1

				if k < q.N then
					pcall(tbl4.Notify, "Analyzer", string.format("%s part %d/%d copied. Paste it, then press the same button", label, k, q.N))
				else
					pcall(tbl4.Notify, "Analyzer", string.format("%s part %d/%d copied. All parts done", label, q.N, q.N))
				end
				return true
			end

			-- server signals: everything that can explain a cancelled delivery
			local function hook(name, fn)
				local remote = networking:FindFirstChild(name)

				if remote and remote:IsA("RemoteEvent") then
					local ok, connection = pcall(function()
						return remote.OnClientEvent:Connect(fn)
					end)

					if ok and connection then
						slicedfn4(function()
							connection:Disconnect()
						end)
					end
				end
			end

			hook("RE/Alerts/Raise", function(...)
				A.Event("alert", { ... })
			end)

			hook("RE/RigSync/Refresh", function(...)
				local args = { ... }
				local first = args[1]

				if type(first) == "table" and first.Action == "Relocate" then
					A.RelocateAt = os.clock()
				end

				if type(first) == "table" and first.Action == "BeginImpulse" then
					A.ImpulseAt = os.clock()
				end

				A.Event("rigsync", args)
			end)

			hook("RE/EggWorld/FieldEggRedeemVerdict", function(...)
				A.Event("verdict", { ... })
			end)

			local eggState = tbl.EggState
			local carryChanged = type(eggState) == "table" and eggState.CarryChanged or nil

			if type(carryChanged) == "table" and type(carryChanged.Connect) == "function" then
				pcall(function()
					local connection = carryChanged:Connect(function(...)
						A.Event("carry", { ... })
					end)

					slicedfn4(function()
						pcall(function()
							connection:Disconnect()
						end)
					end)
				end)
			end

			-- ===== delivery tuning: the hop pacing and the walk speed go back a step after every server rejection and
			-- ===== return to their defaults after clean deliveries =====
			tbl4.MethodStats = {}

			local sc0 = tbl4.SafeCarry
			local Tune = { JumpCap = math.huge, JumpGap = 0.15, Jumped = nil, Ratio = 1.0, Min = 0.85, Max = 1.3, HopRatio = sc0.HopRatio, HopGap = sc0.HopGap, DefaultHopRatio = sc0.HopRatio, DefaultHopGap = sc0.HopGap }
			tbl4.Tune = Tune

			Tune.Apply = function()
				local sc = tbl4.SafeCarry
				sc.EasyRatio = Tune.Ratio
				sc.HopRatio = Tune.HopRatio
				sc.HopGap = Tune.HopGap
			end

			Tune.Learn = function(mode, island, ok, rejected)
				local jumped = Tune.Jumped
				Tune.Jumped = nil

				if mode == "Instant TP" and jumped then
					if ok then
						Tune.JumpCap = math.min(1e6, math.max(Tune.JumpCap, jumped.Longest) * 1.3)
					elseif rejected then
						Tune.JumpCap = math.max(40, math.min(Tune.JumpCap, jumped.Longest) * 0.6)
						Tune.JumpGap = math.min(0.4, Tune.JumpGap + 0.05)
						A.Event("tune", string.format("jump cap %d, gap %.2f", Tune.JumpCap, Tune.JumpGap))
					end
					return
				end

				if ok then
					Tune.Ratio = math.min(Tune.Max, Tune.Ratio + 0.03)
					Tune.HopRatio = math.min(Tune.DefaultHopRatio, Tune.HopRatio + 0.05)
					Tune.HopGap = math.max(Tune.DefaultHopGap, Tune.HopGap - 0.01)
					return
				end

				if not rejected then
					return
				end

				if mode == "Normal" then
					Tune.Ratio = math.max(Tune.Min, Tune.Ratio - 0.05)
				else
					Tune.HopRatio = math.max(0.9, Tune.HopRatio - 0.15)
					Tune.HopGap = math.min(0.2, Tune.HopGap + 0.02)
				end
				A.Event("tune", string.format("hop %.2f every %.2fs, walk %.2f", Tune.HopRatio, Tune.HopGap, Tune.Ratio))
			end
		end

		tbl4.AntiGuard.Handle = sliced2:CreateState({ Name = "Anti Guard Enabled", Default = false })

		pcall(function()
			tbl4.AntiGuard.Enabled = tbl4.AntiGuard.Handle:Get() == true
		end)

		pcall(function()
			tbl4.AntiGuard.Handle:Subscribe(function(arg)
				if type(arg) ~= "boolean" then
					arg = tbl4.AntiGuard.Handle:Get()
				end

				tbl4.AntiGuard.Enabled = arg == true

				-- Anti Guard only runs in Normal mode: while Instant TP / Delivery Stop is selected it switches itself back off
				if tbl4.AntiGuard.Enabled and not tbl4.MethodApplying and tbl4.Method and tbl4.Method.Current() ~= "Normal" then
					tbl4.AntiGuard.Enabled = false
					pcall(tbl4.AntiGuard.Handle.Set, tbl4.AntiGuard.Handle, false)
					if tbl4.NoticeLib and tbl4.NoticeLib.Banner then
						pcall(tbl4.NoticeLib.Banner, "Anti Guard is off while " .. tbl4.Method.Current() .. " is selected", 4)
					end
				end

				if tbl4.StealPanelSync then
					pcall(tbl4.StealPanelSync)
				end

				if tbl4.AntiGuard.Render and tbl4.UiDefer then
					tbl4.UiDefer(function()
						pcall(tbl4.AntiGuard.Render, false)
					end)
				end
			end)
		end)

		tbl4.AntiGuard.PanelHandle = sliced8:CreateToggle({
			Name = "Anti Guard Panel",
			Default = true,
			Callback = function(panelShown)
				if type(panelShown) ~= "boolean" then
					panelShown = tbl4.Toggle(tbl4.AntiGuard.PanelHandle, true)
				end

				tbl4.AntiGuard.PanelShown = panelShown

				if tbl4.AntiGuard.ShowPanel then
					pcall(tbl4.AntiGuard.ShowPanel, panelShown)
				end
			end,
		})

		local sliced14 = nil
		local sliced15 = nil
		local sliced16 = nil
		local str = "None"
		local str2 = "Idle"
		local flag2 = false
		local slicedn5 = 0
		local tbl18 = {}
		local slicedn6 = 20
		local uid = nil
		local slicedfn13

		slicedfn13 = function(arg)
			return arg ~= slicedn5 or not tbl4.Toggle(sliced14, false)
		end

		local slicedfn14

		do
			local tbl19 = {}

			local function slicedfn15(arg)
				if type(arg) ~= "number" or tbl19[arg] then
					return
				end
				tbl19[arg] = true

				task.delay(math.max(0, arg - workspace:GetServerTimeNow()) + 0.05, function()
					tbl19[arg] = nil
					tbl3.Wake()
				end)
			end

			local slicedn7 = 0

			slicedfn14 = function()
				local areaEggCycle = tbl.AreaEggCycle
				if type(areaEggCycle) ~= "table" then
					return nil
				end

				local ok, result, result2, result3, result4 = pcall(function()
					local serverTimeNow = workspace:GetServerTimeNow()
					local nextResetTime = areaEggCycle.NextResetTime
					return serverTimeNow, areaEggCycle.IsNightPhase(serverTimeNow), areaEggCycle.NextNightTime(serverTimeNow), nextResetTime(serverTimeNow)
				end)

				if not ok or type(result4) ~= "number" then
					return nil
				end

				if result2 == true then
					slicedn7 = result4 + tbl4.WallOpenDelay()
					slicedfn15(slicedn7)
					return slicedn7, "night", result
				end

				if tbl4.WallSealed() then
					slicedfn15(result + 0.3)
					return math.max(slicedn7, result), "wall", result
				end

				if type(result3) == "number" and result3 > result then
					slicedfn15(result3)
				end

				return nil
			end
		end

		do
			local areaEggResetWall = tbl.AreaEggResetWall
			local changed = type(areaEggResetWall) == "table" and areaEggResetWall.Changed or nil

			if changed and type(changed.Connect) == "function" then
				local ok, result = pcall(function()
					return changed:Connect(function()
						tbl3.Wake()
					end)
				end)

				if ok and result then
					slicedfn4(function()
						pcall(function()
							result:Disconnect()
						end)
					end)
				end
			end
		end

		local slicedn7 = 8
		local sliced17 = nil
		local slicedn8 = 0
		local slicedfn15, slicedfn16, slicedfn17

		local function slicedfn18(arg)
			local tbl19 = {}
			local str3 = "FirstAreaEgg_" .. tostring(localPlayer.UserId)
			local eggState = tbl.EggState

			if type(eggState) == "table" and type(eggState.ReadFieldEggs) == "function" then
				task.spawn(function()
					local ok, result = pcall(eggState.ReadFieldEggs)

					if ok and type(result) == "table" and type(result.Records) == "table" then
						for _, record in pairs(result.Records) do
							local flag3 = type(record) == "table" and type(record.Uid) == "string"

							if flag3 then
								flag3 = not (arg and string.sub(record.Uid, 1, #str3) == str3)
							end

							if flag3 then
								tbl19[record.Uid] = true
							end
						end
					end
				end)
			end

			return tbl19
		end

		slicedfn15 = function()
			if sliced17 == nil then
				return false
			end

			if tbl4.IsNight() then
				return true
			end

			if slicedn8 == math.huge then
				slicedn8 = os.clock() + slicedn7
			end

			return false
		end

		slicedfn16 = function()
			if sliced17 and slicedn8 == math.huge then
				return
			end
			sliced17 = slicedfn18(true)
			slicedn8 = math.huge
			table.clear(tbl14)
			table.clear(tbl16)
			table.clear(tbl15)
			table.clear(tbl18)
			uid = nil
		end

		slicedfn17 = function()
			if not sliced17 then
				return false
			end

			if os.clock() >= slicedn8 then
				sliced17 = nil
				return false
			end
			local sliced18 = slicedfn18()
			if next(sliced18) == nil then
				return true
			end
			local flag3 = false
			local flag4 = false

			for k in pairs(sliced18) do
				if sliced17[k] then
					flag3 = true
				else
					flag4 = true
				end
			end

			if not flag3 then
				sliced17 = nil
				return false
			end
			return not flag4
		end

		local slicedfn19

		do
			local function slicedfn20(arg)
				local directory = tbl.Assets and tbl.Assets.Directory
				local flag3 = type(directory) == "table" and directory[tostring(arg)] or nil
				local rarity = type(flag3) == "table" and type(flag3.Rarity) == "table" and flag3.Rarity or nil
				local tbl19 = {}

				if rarity then
					rarity = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				tbl19.RarityNumber = rarity or 0
				tbl19.EarningRate = type(flag3) == "table" and tonumber(flag3.EarningRate) or 0
				return tbl19
			end

			local function slicedfn21(arg)
				local mutations = tbl.Mutations

				if type(mutations) == "table" and type(mutations.EarningsFor) == "function" then
					local ok, result = pcall(mutations.EarningsFor, type(arg) == "table" and arg or {})
					if ok and type(result) == "number" then
						return result
					end
				end

				return 1
			end

			local function slicedfn22(arg, arg2)
				local eggRecords = tbl.EggRecords

				if type(eggRecords) == "table" and type(eggRecords.WeightKgForScale) == "function" then
					local ok, result = pcall(eggRecords.WeightKgForScale, arg, arg2)
					if ok and type(result) == "number" then
						return result
					end
				end

				return 0
			end

			slicedfn19 = function(arg, arg2)
				local records = nil
				local eggState = tbl.EggState

				if type(eggState) == "table" and type(eggState.ReadFieldEggs) == "function" then
					task.spawn(function()
						local ok, result = pcall(eggState.ReadFieldEggs)

						if ok and type(result) == "table" and type(result.Records) == "table" and next(result.Records) ~= nil then
							records = result.Records
						end
					end)
				end

				if not records then
					local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")
					if not rfEggWorldAskFieldEggSnapshot or not rfEggWorldAskFieldEggSnapshot:IsA("RemoteFunction") then
						return {}
					end
					local ok, result = pcall(rfEggWorldAskFieldEggSnapshot.InvokeServer, rfEggWorldAskFieldEggSnapshot)
					records = ok and type(result) == "table" and result.Records or nil
				end

				if type(records) ~= "table" then
					return {}
				end
				local tbl19 = {}
				local tbl20 = {}

				for _, record in pairs(records) do
					local uid2 = type(record) == "table" and record.Uid or nil

					if uid2 and record.State ~= "Claimed" then
						tbl20[uid2] = true
					end

					local flag3 = record.State == "Carried" and arg2 == true and arg ~= true and not (tbl4.Steal.Carrying and uid2 == tbl4.Steal.CarryUid)
					local flag4

					if uid2 then
						flag4 = record.State == "Slot" or record.State == "Dropped" or flag3
					else
						flag4 = uid2
					end

					local sliced18 = uid2 and tbl14[uid2] or nil
					local flag5 = uid2 and tbl15[uid2] == true or false
					local flag6 = arg ~= true and flag and uid2 and tbl17[tostring(record.AssetCategory)] or nil
					local flag7 = arg ~= true and tbl4.Steal.RiftPriority == true and uid2 ~= nil and tbl4.Steal.RiftNeeds[tostring(record.AssetCategory)] == true
					local flag8 = arg == true or sliced18 ~= nil or flag5 or flag7 or flag6 ~= nil or tbl12[tostring(record.AreaId)] == true
					local flag9 = arg ~= true and sliced18 == nil and tbl16[uid2] == true
					local flag10 = sliced17 ~= nil and sliced17[uid2] == true
					flag4 = flag4 and typeof(record.BottomCFrame) == "CFrame"
					local flag11

					if flag4 then
						flag11 = (tbl18[uid2] or 0) <= os.clock()
					else
						flag11 = flag4
					end

					if flag11 and flag8 and not flag9 and not flag10 then
						local sliced19 = slicedfn20(record.AssetCategory)
						local str3 = tostring(record.AssetCategory)
						local flag12 = sliced19.RarityNumber >= n
						local flag13 = next(tbl13) == nil or tbl13[str3] == true
						local slicedn9 = tonumber(record.AssetScale) or 1
						local sliced20 = slicedfn21(record.Mutations)
						local slicedn10 = slicedn9 > 5 and (slicedn9 / 5) ^ 1.2 * 19.637875755794113 or slicedn9 ^ 1.85
						local flag14 = slicedn2 <= 0 or sliced19.EarningRate * slicedn10 * sliced20 >= slicedn2
						flag14 = flag12 and flag13 and flag14
						local flag15 = flag7 and not flag14 and not flag5 and sliced18 == nil and flag6 == nil
						local lastSkip = arg ~= true and tbl4.SafeCarry.Unsafe({ Uid = uid2, Category = str3 })

						if lastSkip then
							tbl14[uid2] = nil
							tbl15[uid2] = nil
							tbl4.SafeCarry.LastSkip = lastSkip
						elseif arg == true or sliced18 or flag5 or flag7 or flag6 ~= nil or flag14 then
							table.insert(tbl19, {
								Uid = uid2,
								Category = str3,
								Scale = slicedn9,
								State = record.State,
								Rarity = sliced19.RarityNumber,
								Weight = slicedfn22(record.AssetCategory, slicedn9),
								Mutation = sliced20,
								Value = sliced19.EarningRate * slicedn10 * sliced20,
								CFrame = record.BottomCFrame,
								AreaId = tostring(record.AreaId),
								Rift = arg ~= true and flag7,
								RiftOnly = arg ~= true and flag15,
								Index = flag6,
								Forced = arg ~= true and sliced18 and sliced18.At or nil,
								Priority = arg ~= true and flag5,
							})
						end
					end
				end

				if next(tbl20) ~= nil then
					for k in pairs(tbl14) do
						if not tbl20[k] then
							tbl14[k] = nil
						end
					end

					for k in pairs(tbl15) do
						if not tbl20[k] then
							tbl15[k] = nil
						end
					end

					for k in pairs(tbl16) do
						if not tbl20[k] then
							tbl16[k] = nil
						end
					end
				end

				table.sort(tbl19, function(arg3, arg4)
					if arg3.Forced ~= nil ~= (arg4.Forced ~= nil) then
						return arg3.Forced ~= nil
					end

					if arg3.Forced and arg4.Forced and arg3.Forced ~= arg4.Forced then
						return arg3.Forced < arg4.Forced
					end

					if arg3.Priority ~= arg4.Priority then
						return arg3.Priority == true
					end

					if arg3.RiftOnly ~= arg4.RiftOnly then
						return arg4.RiftOnly == true
					end

					if arg3.Index ~= nil ~= (arg4.Index ~= nil) then
						return arg3.Index ~= nil
					end

					if arg3.Index and arg4.Index and arg3.Index ~= arg4.Index then
						return arg3.Index > arg4.Index
					end

					if sliced4 == tbl5[2] and arg3.Weight ~= arg4.Weight then
						return arg3.Weight > arg4.Weight
					end

					if sliced4 == tbl5[3] and arg3.Mutation ~= arg4.Mutation then
						return arg3.Mutation > arg4.Mutation
					end

					if sliced4 == tbl5[4] and arg3.Value ~= arg4.Value then
						return arg3.Value > arg4.Value
					end

					if sliced4 == tbl5[5] and arg3.Value ~= arg4.Value then
						return arg3.Value < arg4.Value
					end

					if arg3.Rarity ~= arg4.Rarity then
						return arg3.Rarity > arg4.Rarity
					end

					if arg3.Value ~= arg4.Value then
						return arg3.Value > arg4.Value
					end
					return tostring(arg3.Uid) < tostring(arg4.Uid)
				end)

				return tbl19
			end
		end

		local slicedn9 = 6
		local slicedfn20, slicedfn21, slicedfn22, slicedfn23, slicedfn24

		do
			local sliced18 = nil
			local connection = nil

			slicedfn20 = function(arg, arg2, arg3, arg4, arg5)
				local slicedn10 = arg2 - arg.Position
				local magnitude = slicedn10.Magnitude
				local slicedn11 = math.max(arg4, 0.0041666666666666666)
				local vector = Vector3.zero

				if magnitude > 0.01 then
					vector = slicedn10.Unit * math.min(arg3, magnitude / slicedn11)
				end

				local assemblyLinearVelocity = vector + Vector3.new(0, workspace.Gravity * slicedn11 * 0.5, 0)

				if magnitude > 2 then
					if not arg5.mark then
						arg5.mark = magnitude
						arg5.clock = 0
					end

					arg5.clock = arg5.clock + arg4

					if arg5.clock >= 0.4 then
						if arg5.mark - magnitude < arg3 * 0.1 then
							pcall(function()
								arg.CFrame = arg.CFrame + slicedn10.Unit * math.min(magnitude, arg3 * slicedn11)
							end)
						end

						arg5.mark = magnitude
						arg5.clock = 0
					end
				else
					arg5.mark = nil
				end

				pcall(function()
					arg.AssemblyLinearVelocity = assemblyLinearVelocity
					arg.AssemblyAngularVelocity = Vector3.zero
				end)

				return magnitude <= 0.5
			end

			slicedfn21 = function()
				local sliced19 = tbl4.Root()

				if sliced19 then
					pcall(function()
						sliced19.AssemblyLinearVelocity = Vector3.zero
						sliced19.AssemblyAngularVelocity = Vector3.zero
					end)
				end
			end

			local connection2 = nil
			local tbl19 = {}

			slicedfn22 = function()
				sliced18 = nil

				if connection then
					connection:Disconnect()
					connection = nil
				end

				if connection2 then
					connection2:Disconnect()
					connection2 = nil
				end
			end

			slicedfn23 = function()
				local num = tonumber(localPlayer:GetAttribute("RagdollEndTime"))
				return num ~= nil and num > workspace:GetServerTimeNow()
			end

			local flag3 = false

			local function slicedfn25()
				if flag3 then
					return true
				end
				return true
			end

			slicedfn24 = function(arg, arg2)
				sliced18 = arg
				flag3 = arg2 == true
				if connection or not arg then
					return
				end
				tbl19 = {}

				connection = RunService.Heartbeat:Connect(function()
					if not sliced18 or slicedfn25() or slicedfn23() or tbl4.AntiGuard.Busy then
						return
					end
					local sliced19 = tbl4.Root()
					if not sliced19 then
						return
					end

					pcall(function()
						local rotation = sliced19.CFrame.Rotation
						sliced19.CFrame = CFrame.new(sliced18) * rotation
						sliced19.AssemblyLinearVelocity = Vector3.zero
						sliced19.AssemblyAngularVelocity = Vector3.zero
					end)
				end)

				connection2 = RunService.PreSimulation:Connect(function(deltaTime)
					if not sliced18 or not slicedfn25() or slicedfn23() or tbl4.AntiGuard.Busy then
						return
					end
					local sliced19 = tbl4.Root()

					if sliced19 then
						slicedfn20(sliced19, sliced18, 400, deltaTime, tbl19)
					end
				end)
			end
		end

		slicedfn4(slicedfn22)
		local slicedfn25

		slicedfn25 = function()
			slicedfn22()
			tbl4.EndFlight()
			tbl4.GodMode(false)
			local character = localPlayer.Character
			character = character and character:FindFirstChildOfClass("Humanoid")

			if character then
				character.PlatformStand = false
			end
		end

		local slicedn10, slicedfn26, slicedfn27

		do
			local slicedn11 = 1.5
			slicedn10 = 0.6

			local function slicedfn28(arg, arg2)
				local x = arg2.X
				return (Vector3.new(arg.X, 0, arg.Z) - Vector3.new(x, 0, arg2.Z)).Magnitude
			end

			local function slicedfn29(arg)
				local ok, result = pcall(function()
					return arg:GetPivot().Position
				end)

				return ok and result or nil
			end

			slicedfn26 = function(arg, arg2, arg3)
				local sliced18 = slicedfn28(arg.Position, arg3)
				local areaEggSlotsClient = workspace:FindFirstChild("AreaEggSlotsClient")

				if areaEggSlotsClient then
					for _, child in ipairs(areaEggSlotsClient:GetChildren()) do
						if child:IsA("Model") and child.Name ~= arg2 then
							local sliced19 = slicedfn29(child)
							if sliced19 and slicedfn28(sliced19, arg.Position) + slicedn11 < sliced18 then
								return false
							end
						end
					end
				end

				for _, child in ipairs(workspace:GetChildren()) do
					if child:IsA("Model") and child.Name ~= arg2 and #child.Name == 32 and child:FindFirstChild("Hitbox") then
						local sliced19 = slicedfn29(child)
						if sliced19 and slicedfn28(sliced19, arg.Position) + slicedn11 < sliced18 then
							return false
						end
					end
				end

				return true
			end

			tbl4.Steal.WrongEgg = function(carryUid)
				local steal = tbl4.Steal
				if type(carryUid) ~= "string" or not steal.Carrying or steal.CarryUid == carryUid then
					return false
				end
				local eggState = tbl.EggState

				if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
					pcall(eggState.DropFieldEgg, "PlayerRequest")
				end

				local slicedn12 = 0

				while steal.Carrying and slicedn12 < 1 do
					slicedn12 += RunService.Heartbeat:Wait()
				end

				steal.Carrying = false
				steal.CarryUid = carryUid
				return true
			end

			slicedfn27 = function(arg, arg2, arg3)
				local slicedn12 = arg3 or 14
				local sliced18 = nil
				local sliced19 = nil

				for _, child in ipairs(workspace:GetChildren()) do
					if child.Name == "SmartPromptPart" and child:IsA("BasePart") then
						local carryAreaEgg = child:FindFirstChild("CarryAreaEgg")

						if carryAreaEgg and carryAreaEgg:IsA("ProximityPrompt") then
							local sliced20 = slicedfn28(child.Position, arg2)

							if sliced20 < slicedn12 then
								slicedn12 = sliced20
								sliced18 = carryAreaEgg
								sliced19 = child
							end
						end
					end
				end

				if not sliced18 or not sliced19 then
					return nil
				end

				if type(arg) == "string" and not slicedfn26(sliced19, arg, arg2) then
					return nil
				end
				return sliced18, sliced19
			end
		end

		local slicedfn28

		slicedfn28 = function(arg)
			local eggState = tbl.EggState

			if type(arg) == "string" and type(eggState) == "table" and type(eggState.CarryFieldEgg) == "function" then
				pcall(eggState.CarryFieldEgg, arg)
			end
		end

		local slicedfn29

		do
			local function slicedfn30()
				local carryUid = tbl4.Steal.CarryUid
				return type(carryUid) == "string" and carryUid or nil
			end

			local function slicedfn31(arg)
				local sliced18 = slicedfn30()
				if not sliced18 or type(arg) ~= "string" then
					return true
				end
				return sliced18 == arg
			end

			local function slicedfn32(arg)
				if type(arg) ~= "string" then
					return false
				end
				local sliced18 = slicedfn19(false, true)
				if #sliced18 == 0 then
					return true
				end

				for _, sliced19 in ipairs(sliced18) do
					if sliced19.Uid == arg then
						return true
					end
				end

				return false
			end

			local function slicedfn33(arg)
				local eggState = tbl.EggState

				if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
					pcall(eggState.DropFieldEgg, "PlayerRequest")
				end

				local slicedn11 = 0

				while tbl4.Steal.Carrying and slicedn11 < 1 and not slicedfn13(arg) do
					slicedn11 += RunService.Heartbeat:Wait()
				end
			end

			slicedfn29 = function(arg, arg2)
				local slicedn11 = 0

				while not tbl4.Steal.Carrying and slicedn11 < slicedn10 and not slicedfn13(arg2) do
					slicedn11 += RunService.Heartbeat:Wait()
				end

				if not tbl4.Steal.Carrying then
					str2 = "The egg never reached the hand"
					return false
				end

				if slicedfn31(arg) then
					return true
				end
				local sliced18 = slicedfn30()
				if slicedfn32(sliced18) then
					str2 = "Holding another egg that still matches, delivering it"
					return true
				end
				str2 = "Wrong egg in hand, dropping it"
				slicedfn33(arg2)
				return false
			end
		end

		local slicedfn30

		slicedfn30 = function(arg, arg2)
			local eggState = tbl.EggState
			local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
			if not position then
				return false
			end
			local slicedn11 = 0
			local huge = math.huge
			local slicedn12 = 0

			while slicedn11 < 1.5 do
				if slicedfn13(arg2) then
					return false
				end

				if tbl4.Steal.Carrying and not tbl4.Steal.WrongEgg(arg.Uid) then
					return true
				end

				if huge >= 0.06 then
					local sliced18 = slicedfn27(arg.Uid, position)

					if sliced18 then
						pcall(function()
							sliced18.HoldDuration = 0
						end)

						slicedn12 = 0

						if typeof(fireproximityprompt) == "function" then
							pcall(fireproximityprompt, sliced18)
						end
					else
						slicedn12 += 1
						if slicedn12 >= 4 then
							return false
						end

						if type(eggState) == "table" and type(eggState.CarryFieldEgg) == "function" then
							pcall(eggState.CarryFieldEgg, arg.Uid)
						end
					end

					huge = 0
				end

				local result = RunService.Heartbeat:Wait()
				slicedn11 += result
				huge += result
			end

			return tbl4.Steal.Carrying == true
		end

		local slicedfn31

		local sliced18 = slicedfn2(function()
			return ReplicatedStorage.Shared.Modules.Ragdoll
		end)

		slicedfn31 = function()
			local character = localPlayer.Character

			if type(sliced18) == "table" and type(sliced18.IsRagdolled) == "function" then
				local ok, result = pcall(sliced18.IsRagdolled, character)
				if ok and result == true then
					return true
				end
			end

			local num = tonumber(localPlayer:GetAttribute("RagdollEndTime"))
			if num and num > workspace:GetServerTimeNow() then
				return true
			end
			character = character and character:FindFirstChildOfClass("Humanoid")
			if character then
				local state = character:GetState()
				return state == Enum.HumanoidStateType.Physics or state == Enum.HumanoidStateType.Ragdoll or state == Enum.HumanoidStateType.FallingDown
			end
			return false
		end

		local slicedfn32, slicedn11, slicedn12, slicedfn33, stealHome, slicedfn34, slicedfn35

		do
			local function slicedfn36(arg, arg2)
				if tbl4.Steal.Carrying then
					return true
				end
				local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")
				if not rfEggWorldAskFieldEggSnapshot or not rfEggWorldAskFieldEggSnapshot:IsA("RemoteFunction") then
					return false
				end
				local slicedn13 = 0

				while slicedn13 < 1 do
					if slicedfn13(arg2) or tbl4.Steal.Carrying then
						return tbl4.Steal.Carrying == true
					end
					local ok, result = pcall(rfEggWorldAskFieldEggSnapshot.InvokeServer, rfEggWorldAskFieldEggSnapshot)
					ok = ok and type(result) == "table" and result.Records or nil

					if type(ok) == "table" then
						local flag3 = false

						for _, sliced19 in pairs(ok) do
							if type(sliced19) == "table" and sliced19.Uid == arg and (sliced19.State == "Slot" or sliced19.State == "Dropped") then
								flag3 = true
								break
							end
						end

						if not flag3 then
							return tbl4.Steal.Carrying == true
						end
					end

					slicedn13 += task.wait(0.3)
				end

				return tbl4.Steal.Carrying == true
			end

			local function slicedfn37(arg)
				local sliced19 = tbl4.Root()
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not sliced19 or not position then
					return math.huge
				end
				return (sliced19.Position - position).Magnitude
			end

			slicedfn32 = function(arg)
				local huge = math.huge
				local sliced19 = nil

				for _, sliced20 in ipairs(arg) do
					local sliced21 = slicedfn37(sliced20)

					if sliced21 < huge then
						huge = sliced21
						sliced19 = sliced20
					end
				end

				return sliced19, huge
			end

			slicedn11 = 20
			slicedn12 = 90
			local slicedn13 = 6

			slicedfn33 = function(arg, arg2, arg3, arg4, arg5, arg6)
				slicedfn22()
				local sliced19 = tbl4.Root()
				if not sliced19 then
					return false
				end
				local character = localPlayer.Character
				local position = sliced19.Position
				local tbl19 = {}
				local position2 = nil
				local flag3 = nil
				local str3 = nil
				local slicedn14 = 0

				local function slicedfn38()
					if arg4 ~= nil then
						return true
					end
					return true
				end

				local function slicedfn39(arg7)
					slicedn14 += arg7
					if slicedfn13(arg2) then
						flag3 = false
						return nil
					end

					if arg3 and not tbl4.Steal.Carrying then
						flag3 = false
						str3 = "dropped"
						return nil
					end

					if arg6 then
						local sliced20 = arg6()

						if sliced20 then
							flag3 = false
							str3 = sliced20
							return nil
						end
					end

					local sliced20 = tbl4.Root()

					if not sliced20 or slicedn14 >= 25 or localPlayer.Character ~= character then
						flag3 = false
						str3 = "respawned"
						return nil
					end

					return sliced20
				end

				local connection = RunService.Heartbeat:Connect(function(deltaTime)
					if flag3 ~= nil or slicedfn38() or tbl4.AntiGuard.Busy then
						return
					end
					local sliced20 = slicedfn39(deltaTime)
					if not sliced20 then
						return
					end

					if slicedn9 < (sliced20.Position - position).Magnitude then
						if arg5 then
							flag3 = false
							str3 = "displaced"
							return
						end

						position = sliced20.Position
					end

					local slicedn15 = (arg4 or 400) * (os.clock() < (tbl4.SafeCarry.SlowUntil or 0) and tbl4.SafeCarry.SlowFactor or 1)
					local slicedn16

					if tbl4.SafeCarry.Enabled and tbl4.SafeCarry.Pace then
						slicedn16 = math.min(slicedn15, tbl4.SafeCarry.Pace())
					else
						slicedn16 = slicedn15
					end

					local slicedn17 = arg - position
					local slicedn18 = slicedn16 * deltaTime
					local flag4 = slicedn17.Magnitude <= math.max(slicedn18, 0.05)
					position = flag4 and arg or position + slicedn17.Unit * slicedn18
					local vector = Vector3.new(slicedn17.X, 0, slicedn17.Z)
					local cframe = vector.Magnitude > 0.05 and CFrame.lookAt(Vector3.zero, vector.Unit) or sliced20.CFrame.Rotation

					pcall(function()
						sliced20.CFrame = CFrame.new(position) * cframe
						sliced20.AssemblyLinearVelocity = Vector3.zero
						sliced20.AssemblyAngularVelocity = Vector3.zero
					end)

					if flag4 then
						flag3 = true
					end
				end)

				local connection2 = RunService.PreSimulation:Connect(function(deltaTime)
					if flag3 ~= nil or not slicedfn38() or tbl4.AntiGuard.Busy then
						return
					end
					local sliced20 = slicedfn39(deltaTime)
					if not sliced20 then
						return
					end
					local slicedn15 = (arg4 or 400) * (os.clock() < (tbl4.SafeCarry.SlowUntil or 0) and tbl4.SafeCarry.SlowFactor or 1)
					local slicedn16

					if tbl4.SafeCarry.Enabled and tbl4.SafeCarry.Pace then
						slicedn16 = math.min(slicedn15, tbl4.SafeCarry.Pace())
					else
						slicedn16 = slicedn15
					end

					if arg5 and position2 and (sliced20.Position - position2).Magnitude > slicedn9 + slicedn16 * deltaTime then
						flag3 = false
						str3 = "displaced"
						return
					end

					if slicedfn20(sliced20, arg, slicedn16, deltaTime, tbl19) then
						flag3 = true
					end

					position2 = sliced20.Position
					position = sliced20.Position
				end)

				while flag3 == nil do
					RunService.Heartbeat:Wait()
				end

				connection:Disconnect()
				connection2:Disconnect()

				if slicedfn38() and not flag3 then
					slicedfn21()
				end

				if flag3 then
					slicedfn24(arg, arg4 ~= nil)
				end

				return flag3, str3
			end

			local tbl19 = {
				{
					Path = { "GearGiver_Slap", "Podium" },
					Offset = Vector3.new(-16.415, 21.072, -6.106),
				},
				{
					Path = { "World", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" },
					Offset = Vector3.new(-26.776, 1.75, 18.665),
				},
				{
					Path = { "__OBJECTS", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" },
					Offset = Vector3.new(-26.776, 1.75, 18.665),
				},
			}

			stealHome = function()
				for _, sliced19 in ipairs(tbl19) do
					local sliced20 = workspace

					for _, sliced21 in ipairs(sliced19.Path) do
						sliced20 = sliced20 and sliced20:FindFirstChild(sliced21) or nil
					end

					if sliced20 and sliced20:IsA("BasePart") then
						return sliced20.CFrame:PointToWorldSpace(sliced19.Offset)
					end
				end

				return Vector3.new(528.7, 70.57, -364.11)
			end

			tbl4.StealHome = stealHome

			tbl4.InsideBase = function(arg)
				if not arg then
					arg = tbl4.Root()
					arg = arg and arg.Position
				end

				if arg == nil then
					return false
				end
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				local areas = world and world:FindFirstChild("Areas")
				areas = areas and areas:FindFirstChild("SeparationLine")
				return arg.X < (areas and areas:IsA("BasePart") and areas.Position.X or 552)
			end

			local function slicedfn38(arg)
				if tbl4.AntiGuard.Busy then
					return false
				end
				local character = localPlayer.Character
				local sliced19 = tbl4.Root()
				if not character or not sliced19 then
					return false
				end
				local rotation = sliced19.CFrame.Rotation
				local cFrame = CFrame.new(arg) * rotation

				pcall(function()
					character:PivotTo(cFrame)
				end)

				if (sliced19.Position - arg).Magnitude > 3 then
					pcall(function()
						sliced19.CFrame = cFrame
					end)
				end

				for _, descendant in ipairs(character:GetDescendants()) do
					if descendant:IsA("BasePart") then
						pcall(function()
							descendant.AssemblyLinearVelocity = Vector3.zero
							descendant.AssemblyAngularVelocity = Vector3.zero
						end)
					end
				end

				return true
			end

			local function slicedfn39(arg)
				if tbl4.AntiGuard.Busy then
					return
				end
				local character = localPlayer.Character
				local sliced19 = tbl4.Root()
				if not character or not sliced19 or not arg then
					return
				end

				if (sliced19.Position - arg).Magnitude > 6 then
					slicedfn38(arg)
					return
				end

				for _, descendant in ipairs(character:GetDescendants()) do
					if descendant:IsA("BasePart") and descendant ~= sliced19 and (descendant.Position - sliced19.Position).Magnitude > 12 then
						pcall(function()
							descendant.CFrame = sliced19.CFrame
							descendant.AssemblyLinearVelocity = Vector3.zero
						end)
					end
				end
			end

			local function slicedfn40(arg, arg2)
				local slicedn14 = 0

				while true do
					if not (slicedn14 < slicedn13) then
						return not slicedfn13(arg)
					else
						if slicedfn13(arg) then
							break
						end
						local character = localPlayer.Character
						local flag3 = slicedfn31()

						if not flag3 and character then
							for _, descendant in ipairs(character:GetDescendants()) do
								if descendant:IsA("Constraint") and string.find(descendant.Name, "RagdollConstraint", 1, true) then
									flag3 = true
									break
								end
							end
						end

						if not flag3 then
							return not slicedfn13(arg)
						end
						slicedfn39(arg2)
						slicedn14 += RunService.Heartbeat:Wait()
					end
				end

				return false
			end

			local function slicedfn41(arg)
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("GuardAreas")
				local areaId = world and arg and arg.AreaId and world:FindFirstChild(arg.AreaId)
				return areaId and areaId:FindFirstChild("Guard") or nil
			end

			slicedfn34 = function(arg)
				local sliced19 = slicedfn41(arg)
				return sliced19 ~= nil and sliced19:GetAttribute("GuardState") == "Sleeping"
			end

			local slicedn14 = 3

			slicedfn35 = function(arg)
				local sliced19 = slicedfn41(arg)
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not sliced19 or not position then
					return nil, nil
				end

				local ok, result = pcall(function()
					return sliced19:GetPivot().Position
				end)

				if not ok then
					return nil, nil
				end
				local vector = Vector3.new(position.X - result.X, 0, position.Z - result.Z)
				if vector.Magnitude < 0.1 then
					return nil, nil
				end
				local slicedn15 = result + vector.Unit * slicedn14
				return Vector3.new(slicedn15.X, position.Y + 3, slicedn15.Z), result
			end

			local function slicedfn42(arg, arg2)
				local tbl20 = { Landed = false, Destination = arg2 }
				local antiGuard = tbl4.AntiGuard
				antiGuard.HitArms = antiGuard.HitArms + 1
				tbl4.AntiGuard.HitArmedAt = os.clock()

				tbl20.Link = localPlayer:GetAttributeChangedSignal("RagdollEndTime"):Connect(function()
					if tbl20.Landed or slicedfn13(arg) then
						return
					end
					local num = tonumber(localPlayer:GetAttribute("RagdollEndTime"))
					if not num or num <= workspace:GetServerTimeNow() then
						return
					end
					local sliced19 = tbl4.Root()
					if not sliced19 then
						return
					end
					tbl20.Landed = true
					slicedfn22()
					tbl4.SafeCarry.JumpDistance = (tbl20.Destination - sliced19.Position).Magnitude
					tbl4.SafeCarry.JumpAt = os.clock()

					pcall(function()
						sliced19.CFrame = CFrame.new(tbl20.Destination)
						sliced19.AssemblyLinearVelocity = Vector3.zero
					end)
				end)

				tbl20.Stop = function()
					if tbl20.Link then
						tbl20.Link:Disconnect()
						tbl20.Link = nil
						tbl4.AntiGuard.HitArms = math.max(0, tbl4.AntiGuard.HitArms - 1)
					end
				end

				return tbl20
			end

			local function slicedfn43(arg, arg2, arg3)
				local character = localPlayer.Character
				character = character and character:FindFirstChildOfClass("Humanoid")

				if character then
					character.PlatformStand = false
				end

				local slicedn15 = 0
				local sliced19 = nil

				while not arg2.Landed and slicedn15 < slicedn11 do
					if slicedfn13(arg) then
						break
					end

					if arg3 then
						arg3(arg2)
					end

					if not tbl4.Steal.Carrying then
						sliced19 = sliced19 or slicedn15
						if slicedn15 - sliced19 > 1 then
							break
						end
					end

					slicedn15 += RunService.Heartbeat:Wait()
				end

				arg2.Stop()
				return arg2.Landed
			end

			local slicedn15 = 20

			local function slicedfn44(arg, arg2, arg3, arg4)
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not position then
					return false
				end
				local slicedn16 = 0
				local huge = math.huge

				while slicedn16 < arg3 do
					if slicedfn13(arg2) then
						return false
					end

					if tbl4.Steal.Carrying and not tbl4.Steal.WrongEgg(arg.Uid) then
						return true
					end

					if huge >= 0.1 then
						local sliced19 = slicedfn27(arg.Uid, position)

						if sliced19 then
							pcall(function()
								sliced19.HoldDuration = 0
							end)

							if typeof(fireproximityprompt) == "function" then
								pcall(fireproximityprompt, sliced19)
							end
						else
							slicedfn28(arg.Uid)
						end

						huge = 0
					end

					if arg4 then
						slicedfn39(arg4)
					end

					local result = RunService.Heartbeat:Wait()
					slicedn16 += result
					huge += result
				end

				return tbl4.Steal.Carrying == true
			end

			local function slicedfn45(arg, arg2, arg3, arg4)
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not position then
					return false
				end
				local slicedn16 = position + Vector3.new(0, 3, 0)
				local character = localPlayer.Character
				local humanoid = character and character:FindFirstChildOfClass("Humanoid")

				if humanoid and character:FindFirstChildWhichIsA("Tool") then
					pcall(function()
						humanoid:UnequipTools()
					end)
				end

				if arg3 then
					slicedfn24(slicedn16, true)
					str2 = "Waiting to stand up"
					if not slicedfn40(arg2, slicedn16) then
						return false
					end

					if tbl4.SafeCarry.Enabled and arg4 == nil and tbl4.SafeCarry.Settle then
						if not tbl4.SafeCarry.Settle(arg2, arg) then
							return false
						end
					end
				else
					str2 = "Jumping to the egg"
					local sliced19 = tbl4.Root()

					if sliced19 and (slicedn16 - sliced19.Position).Magnitude <= slicedn12 then
						pcall(function()
							local rotation = sliced19.CFrame.Rotation
							sliced19.CFrame = CFrame.new(slicedn16) * rotation
							sliced19.AssemblyLinearVelocity = Vector3.zero
							sliced19.AssemblyAngularVelocity = Vector3.zero
						end)
					elseif not slicedfn33(slicedn16, arg2, nil, 400) then
						return false
					end
				end

				if slicedfn13(arg2) then
					return false
				end
				local flag3 = arg4 and typeof(arg4.CFrame) == "CFrame"
				local sliced19 = nil

				if flag3 then
					sliced19 = slicedfn42(arg2, arg4.CFrame.Position + Vector3.new(0, 3, 0))
				end

				local str3 = "FirstAreaEgg_" .. tostring(localPlayer.UserId)
				local flag4 = type(arg.Uid) == "string" and string.sub(arg.Uid, 1, #str3) == str3 and string.match(arg.Uid, "_([%w ]+:Slot_%d+)$") or nil
				arg4 = arg4 and flag4
				local flag5 = false

				if arg4 then
					local eggState = tbl.EggState

					if type(eggState) == "table" and type(eggState.CarryFieldEgg) == "function" then
						str2 = "Taking the starter egg"

						task.spawn(function()
							pcall(eggState.CarryFieldEgg, arg.Uid, flag4)
						end)

						local slicedn17 = 0

						while not tbl4.Steal.Carrying and slicedn17 < 0.8 do
							if slicedfn13(arg2) then
								return false
							end
							slicedn17 += RunService.Heartbeat:Wait()
						end

						flag5 = tbl4.Steal.Carrying == true
					end
				end

				if not flag5 then
					str2 = "Taking the egg"
					flag5 = slicedfn30(arg, arg2)

					if not flag5 and not slicedfn13(arg2) then
						slicedfn33(slicedn16, arg2, nil, 400)
						flag5 = slicedfn30(arg, arg2)
					end
				end

				if not flag5 and not slicedfn36(arg.Uid, arg2) then
					if sliced19 then
						sliced19.Stop()
					end

					tbl18[arg.Uid] = os.clock() + slicedn6
					str2 = "That egg would not come free"
					return false
				end

				if sliced19 then
					local reGuardPatrolForestStrike = networking:FindFirstChild("RE/GuardPatrol/ForestStrike")
					local sliced20 = slicedfn41(arg) or slicedfn41({ AreaId = "Forest" })
					local humanoidRootPart = sliced20 and sliced20:FindFirstChild("HumanoidRootPart")

					if reGuardPatrolForestStrike and reGuardPatrolForestStrike:IsA("RemoteEvent") and humanoidRootPart then
						str2 = "Calling the guard strike"

						pcall(function()
							reGuardPatrolForestStrike:FireServer({ EggUid = arg.Uid, GuardCFrame = humanoidRootPart.CFrame })
						end)
					end
				end

				tbl4.Steal.LastFinishedAt = os.clock()
				return true, sliced19
			end

			local huge = math.huge
			local huge2 = math.huge

			local function slicedfn46(arg, arg2, arg3)
				local sliced19 = nil
				local sliced20 = nil

				for _, child in ipairs(workspace:GetChildren()) do
					if child.Name == "SmartPromptPart" and child:IsA("BasePart") then
						local carryAreaEgg = child:FindFirstChild("CarryAreaEgg")

						if carryAreaEgg and carryAreaEgg:IsA("ProximityPrompt") then
							local magnitude = (child.Position - arg).Magnitude

							if magnitude < arg2 then
								arg2 = magnitude
								sliced19 = carryAreaEgg
								sliced20 = child
							end
						end
					end
				end

				if sliced19 and sliced20 and type(arg3) == "string" and not slicedfn26(sliced20, arg3, arg) then
					return nil
				end
				return sliced19, sliced20
			end

			local function slicedfn47(arg)
				local areaEggSlotsClient = workspace:FindFirstChild("AreaEggSlotsClient")
				local sliced19 = workspace:FindFirstChild(arg) or areaEggSlotsClient and areaEggSlotsClient:FindFirstChild(arg)
				if not sliced19 then
					return nil
				end

				local ok, result = pcall(function()
					return sliced19:GetPivot().Position
				end)

				return ok and result or nil
			end

			local function slicedfn48(arg)
				local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")
				if not rfEggWorldAskFieldEggSnapshot or not rfEggWorldAskFieldEggSnapshot:IsA("RemoteFunction") then
					return nil
				end
				local ok, result = pcall(rfEggWorldAskFieldEggSnapshot.InvokeServer, rfEggWorldAskFieldEggSnapshot)
				local records = ok and type(result) == "table" and result.Records or nil
				if type(records) ~= "table" then
					return nil
				end

				for _, record in pairs(records) do
					if type(record) == "table" and record.Uid == arg and typeof(record.BottomCFrame) == "CFrame" then
						return record.BottomCFrame.Position, true
					end
				end

				return nil, true
			end

			local function slicedfn49(arg)
				local sliced19 = workspace:FindFirstChild(arg)
				if not sliced19 then
					return false
				end

				for _, descendant in ipairs(sliced19:GetDescendants()) do
					if descendant:IsA("JointInstance") or descendant:IsA("WeldConstraint") or descendant:IsA("RigidConstraint") then
						local ok, result, result2 = pcall(function()
							return descendant.Part0, descendant.Part1
						end)

						if ok then
							for _, sliced20 in ipairs({ result, result2 }) do
								if typeof(sliced20) == "Instance" and not sliced20:IsDescendantOf(sliced19) then
									local model = sliced20:FindFirstAncestorOfClass("Model")
									if model and model ~= localPlayer.Character and Players:GetPlayerFromCharacter(model) then
										return true
									end
								end
							end
						end
					end
				end

				return false
			end

			local function slicedfn50(arg, arg2)
				local state = 1
				local sliced19, carryUid, slicedn16, vector, connection, slicedn17, slicedn18, huge3, sliced20, sliced21, slicedn19, huge4, flag3, sliced22, sliced23, sliced24, sliced25, now, flag4, slicedn20, flag5, sliced26

				while true do
					if state == 1 then
						sliced19 = arg
						carryUid = arg2

						if carryUid then
							state = 3
						else
							state = 2
						end
					elseif state == 2 then
						carryUid = tbl4.Steal.CarryUid
						state = 3
					elseif state == 3 then
						if type(carryUid) ~= "string" then
							state = 50
						else
							state = 4
						end
					elseif state == 4 then
						slicedfn22()
						str2 = "Following the egg"
						slicedn16 = nil
						vector = Vector3.zero

						connection = RunService.PreSimulation:Connect(function(deltaTime)
							local sliced27 = tbl4.Root()
							if not sliced27 or not slicedn16 or tbl4.Steal.Carrying or slicedfn13(sliced19) then
								return
							end

							if slicedfn23() then
								if not tbl4.SafeCarry.Enabled and (sliced27.Position - slicedn16).Magnitude > 2 then
									slicedfn38(slicedn16)
								end

								return
							end

							local slicedn21 = math.max(deltaTime, 0.0041666666666666666)
							local slicedn22 = vector + (slicedn16 - sliced27.Position) / math.max(0.08, slicedn21)
							local enabled = tbl4.SafeCarry.Enabled and tbl4.SafeCarry.Pace() or slicedn4 + vector.Magnitude


							if slicedn22.Magnitude > enabled then
								slicedn22 = slicedn22.Unit * enabled
							end

							local assemblyLinearVelocity = slicedn22 + Vector3.new(0, workspace.Gravity * slicedn21 * 0.5, 0)

							pcall(function()
								sliced27.AssemblyLinearVelocity = assemblyLinearVelocity
								sliced27.AssemblyAngularVelocity = Vector3.zero
							end)
						end)

						slicedn17 = 0
						slicedn18 = 0
						huge3 = math.huge
						sliced20 = nil
						sliced21 = nil
						slicedn19 = 0
						huge4 = math.huge
						state = 5
					elseif state == 5 then
						flag3 = false

						if not (slicedn17 < huge2) then
							state = 47
						else
							state = 6
						end
					elseif state == 6 then
						if slicedfn13(sliced19) then
							state = 47
						else
							state = 7
						end
					elseif state == 7 then
						if tbl4.Steal.Carrying then
							state = 8
						else
							state = 11
						end
					elseif state == 8 then
						if tbl4.Steal.WrongEgg(carryUid) then
							state = 10
						else
							state = 9
						end
					elseif state == 9 then
						flag3 = true
						state = 47
					elseif state == 10 then
						str2 = "Picked up the wrong egg, dropped it"
						state = 11
					elseif state == 11 then
						sliced22 = tbl4.Root()

						if not sliced22 then
							state = 47
						else
							state = 12
						end
					elseif state == 12 then
						sliced23 = slicedfn47(carryUid)

						if sliced23 then
							state = 21
						else
							state = 13
						end
					elseif state == 13 then
						if huge3 >= 0.5 then
							state = 14
						else
							state = 22
						end
					elseif state == 14 then
						sliced24, sliced25 = slicedfn48(carryUid)

						if sliced24 then
							state = 20
						else
							state = 15
						end
					elseif state == 15 then
						huge3 = 0

						if sliced25 then
							state = 17
						else
							state = 16
						end
					elseif state == 16 then
						sliced23 = sliced24
						state = 22
					elseif state == 17 then
						slicedn18 += 1

						if not (slicedn18 >= 4) then
							state = 19
						else
							state = 18
						end
					elseif state == 18 then
						str2 = "The egg is gone"
						state = 47
					elseif state == 19 then
						sliced23 = sliced24
						state = 22
					elseif state == 20 then
						slicedn18 = 0
						huge3 = 0
						sliced23 = sliced24
						state = 22
					elseif state == 21 then
						slicedn18 = 0
						state = 22
					elseif state == 22 then
						if sliced23 then
							state = 23
						else
							state = 32
						end
					elseif state == 23 then
						now = os.clock()

						if sliced20 then
							state = 25
						else
							state = 24
						end
					elseif state == 24 then
						flag4 = sliced20
						state = 26
					elseif state == 25 then
						flag4 = sliced21
						state = 26
					elseif state == 26 then
						if flag4 then
							state = 27
						else
							state = 28
						end
					elseif state == 27 then
						flag4 = now > sliced21
						state = 28
					elseif state == 28 then
						if flag4 then
							state = 29
						else
							state = 31
						end
					elseif state == 29 then
						slicedn20 = (sliced23 - sliced20) / math.max(now - sliced21, 0.0041666666666666666)

						if not (slicedn20.Magnitude < 3000) then
							state = 31
						else
							state = 30
						end
					elseif state == 30 then
						vector = vector:Lerp(slicedn20, 0.3)
						state = 31
					elseif state == 31 then
						slicedn16 = sliced23 + Vector3.new(0, 3, 0)
						sliced20 = sliced23
						sliced21 = now
						state = 32
					elseif state == 32 then
						if not (slicedn19 >= 0.4) then
							state = 36
						else
							state = 33
						end
					elseif state == 33 then
						if slicedfn49(carryUid) then
							state = 35
						else
							state = 34
						end
					elseif state == 34 then
						str2 = "Egg dropped, taking it back"
						slicedn19 = 0
						state = 36
					elseif state == 35 then
						str2 = "Another player has the egg, following it until it drops"
						slicedn19 = 0
						state = 36
					elseif state == 36 then
						if slicedn16 then
							state = 38
						else
							state = 37
						end
					elseif state == 37 then
						flag5 = slicedn16
						state = 39
					elseif state == 38 then
						flag5 = (slicedn16 - sliced22.Position).Magnitude <= (tbl4.SafeCarry.Teleport and 30 or slicedn15)
						state = 39
					elseif state == 39 then
						if flag5 then
							state = 40
						else
							state = 41
						end
					elseif state == 40 then
						flag5 = huge4 >= (tbl4.SafeCarry.Teleport and 0.03 or 0.1)
						state = 41
					elseif state == 41 then
						if flag5 then
							state = 42
						else
							state = 46
						end
					elseif state == 42 then
						sliced26 = slicedfn46(slicedn16 - Vector3.new(0, 3, 0), tbl4.SafeCarry.Teleport and 10 or 6, carryUid)

						if sliced26 then
							state = 44
						else
							state = 43
						end
					elseif state == 43 then
						task.spawn(slicedfn28, carryUid)
						huge4 = 0
						state = 46
					elseif state == 44 then
						pcall(function()
							sliced26.HoldDuration = 0
						end)

						huge4 = 0

						if typeof(fireproximityprompt) ~= "function" then
							state = 46
						else
							state = 45
						end
					elseif state == 45 then
						pcall(fireproximityprompt, sliced26)

						-- Instant TP: also send the take request itself, both ways at once
						if tbl4.SafeCarry.Teleport then
							task.spawn(slicedfn28, carryUid)
						end
						state = 46
					elseif state == 46 then
						local result = RunService.Heartbeat:Wait()
						slicedn17 += result
						huge4 += result
						huge3 += result
						slicedn19 += result
						state = 5
					elseif state == 47 then
						connection:Disconnect()
						slicedfn21()

						if flag3 then
							state = 49
						else
							state = 48
						end
					elseif state == 48 then
						flag3 = tbl4.Steal.Carrying == true
						state = 49
					elseif state == 49 then
						return flag3
					elseif state == 50 then
						return false
					end
				end
			end

			local function slicedfn51(arg, arg2)
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not position then
					return false
				end

				if tbl4.InsideBase() and not tbl4.InsideBase(position) then
					local sliced19 = stealHome()

					if sliced19 then
						str2 = "Leaving the base through the safe zone"
						if not slicedfn33(sliced19 + Vector3.new(0, 3, 0), arg2, nil, 400) then
							return false
						end
					end
				end

				str2 = "Flying to the egg"
				if not slicedfn33(position + Vector3.new(0, 3, 0), arg2, nil, 400) then
					return false
				end
				str2 = "Taking the egg"
				local sliced19 = slicedfn44(arg, arg2, 0.6, nil)

				if not sliced19 and not slicedfn13(arg2) then
					sliced19 = slicedfn30(arg, arg2)
				end

				if not sliced19 and not slicedfn36(arg.Uid, arg2) then
					tbl18[arg.Uid] = os.clock() + slicedn6
					return false
				end
				tbl4.Steal.LastFinishedAt = os.clock()
				return true
			end

			local tbl20 = { Uid = nil, Freed = nil, Token = nil }
			local slicedn16 = 3

			local function slicedfn52()
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("GuardAreas")
				local sliced19 = tbl4.Root()
				if not world or not sliced19 then
					return nil
				end
				local str3 = tostring(localPlayer.UserId)
				local carryAreaId = tbl4.Steal.CarryAreaId and slicedfn41({ AreaId = tostring(tbl4.Steal.CarryAreaId) }) or nil
				local huge3 = math.huge
				local sliced20 = nil

				for _, child in ipairs(world:GetChildren()) do
					local guard = child:FindFirstChild("Guard")

					if guard then
						if tostring(guard:GetAttribute("TargetPlayer")) == str3 or tostring(guard:GetAttribute("WakeTargetPlayer")) == str3 then
							return guard
						end

						local ok, result = pcall(function()
							return guard:GetPivot().Position
						end)

						if ok then
							local magnitude = (result - sliced19.Position).Magnitude

							if magnitude < huge3 then
								sliced20 = guard
								huge3 = magnitude
							end
						end
					end
				end

				return carryAreaId or sliced20
			end

			local function slicedfn53(arg, arg2, arg3)
				local sliced19 = slicedfn52()
				if not sliced19 then
					return false
				end
				local sliced20 = slicedfn42(arg, arg3 + Vector3.new(0, 3, 0))
				local slicedn17 = 0

				while true do
					if not sliced20.Landed and slicedn17 < slicedn11 and not slicedfn13(arg) then
						local ok, result = pcall(function()
							return sliced19:GetPivot().Position
						end)

						local sliced21 = tbl4.Root()

						if not (not ok or not sliced21) then
							if slicedn14 + 5 < (result - sliced21.Position).Magnitude then
								local vector = Vector3.new(sliced21.Position.X - result.X, 0, sliced21.Position.Z - result.Z)
								local slicedn18 = result + (vector.Magnitude > 0.1 and vector.Unit * slicedn14 or Vector3.zero)

								slicedfn33(Vector3.new(slicedn18.X, result.Y + 3, slicedn18.Z), arg, nil, 400, true, function()
									if sliced20.Landed then
										return "hit"
									end
									return nil
								end)
							end

							slicedn17 += RunService.Heartbeat:Wait()
							continue
						end
					end

					break
				end

				sliced20.Stop()
				if not sliced20.Landed then
					return false
				end
				return slicedfn50(arg, arg2)
			end

			tbl4.SafeCarry.Dangers = {}
			tbl4.SafeCarry.DangerAt = 0

			tbl4.SafeCarry.RefreshDangers = function()
				local safeCarry = tbl4.SafeCarry
				local dangerAt = safeCarry.DangerAt
				if os.clock() - dangerAt < 1 then
					return safeCarry.Dangers
				end
				safeCarry.DangerAt = os.clock()
				local dangers = {}

				local function slicedfn54(arg)
					local ok, result, result2 = pcall(function()
						if arg:IsA("Model") then
							return arg:GetBoundingBox()
						end

						if arg:IsA("BasePart") then
							return arg.CFrame, arg.Size
						end
					end)

					if ok and result and result2 then
						local abs = math.abs
						local z = result2.Z
						local slicedn17 = Vector3.new(math.abs(result2.X), 0, abs(z)) * 0.5
						local sliced19 = (result - result.Position):VectorToWorldSpace(slicedn17)
						local x = slicedn17.X
						local z2 = slicedn17.Z
						local slicedn18 = math.max(math.abs(sliced19.X), x, z2)
						local x2 = slicedn17.X
						local z3 = slicedn17.Z
						local slicedn19 = math.max(math.abs(sliced19.Z), x2, z3)

						table.insert(dangers, {
							MinX = result.Position.X - slicedn18,
							MaxX = result.Position.X + slicedn18,
							MinZ = result.Position.Z - slicedn19,
							MaxZ = result.Position.Z + slicedn19,
							Name = arg.Name,
						})
					end
				end

				local function slicedfn55(arg)
					if arg == "ScrambleLocalVisuals" or arg == "DrScrambleEvent" then
						return false
					end
					local sliced19 = string.lower(arg)
					return string.find(sliced19, "portal", 1, true) or string.find(sliced19, "teleport", 1, true) or string.find(sliced19, "mech", 1, true) or string.find(sliced19, "arena", 1, true) or string.find(sliced19, "scramble", 1, true)
				end

				for _, child in ipairs(workspace:GetChildren()) do
					if (child:IsA("Model") or child:IsA("BasePart") or child:IsA("Folder")) and slicedfn55(child.Name) then
						if child:IsA("Folder") then
							for _, child2 in ipairs(child:GetChildren()) do
								slicedfn54(child2)
							end
						else
							slicedfn54(child)
						end
					end
				end

				local world = workspace:FindFirstChild("World")
				world = world and world:FindFirstChild("Build")

				if world then
					for _, child in ipairs(world:GetChildren()) do
						if slicedfn55(child.Name) then
							for _, child2 in ipairs(child:GetChildren()) do
								slicedfn54(child2)
							end
						end
					end
				end

				safeCarry.Dangers = dangers
				return dangers
			end

			tbl4.SafeCarry.Avoid = function(arg, arg2)
				for _, sliced19 in ipairs(tbl4.SafeCarry.RefreshDangers()) do
					local slicedn17 = sliced19.MinX - 12
					local slicedn18 = sliced19.MaxX + 12
					local slicedn19 = sliced19.MinZ - 12
					local slicedn20 = sliced19.MaxZ + 12
					local sliced20, sliced21, sliced22 = ipairs({ { arg.X, arg2.X - arg.X, slicedn17, slicedn18 }, { arg.Z, arg2.Z - arg.Z, slicedn19, slicedn20 } })
					local flag3 = true
					local slicedn21 = 0
					local slicedn22 = 1

					for _, sliced23 in sliced20, sliced21, sliced22 do
						local sliced24 = sliced23[1]
						local sliced25 = sliced23[2]
						local sliced26 = sliced23[3]
						local sliced27 = sliced23[4]

						if math.abs(sliced25) < 1e-06 then
							if sliced24 < sliced26 or sliced24 > sliced27 then
								flag3 = false
							end
						else
							local slicedn23 = (sliced26 - sliced24) / sliced25
							local slicedn24 = (sliced27 - sliced24) / sliced25
							local sliced28, sliced29

							if slicedn23 > slicedn24 then
								sliced28 = slicedn24
								sliced29 = slicedn23
							else
								sliced28 = slicedn23
								sliced29 = slicedn24
							end

							local slicedn25 = math.max(slicedn21, sliced28)
							local slicedn26 = math.min(slicedn22, sliced29)

							if slicedn25 > slicedn26 then
								flag3 = false
								slicedn21 = slicedn25
								slicedn22 = slicedn26
							else
								slicedn21 = slicedn25
								slicedn22 = slicedn26
							end
						end
					end

					if flag3 and not (arg.X >= slicedn17 and arg.X <= slicedn18 and arg.Z >= slicedn19 and arg.Z <= slicedn20) then
						local slicedn23 = slicedn19 - 2
						local slicedn24 = slicedn20 + 2
						local flag4 = math.abs(arg.Z - slicedn23) <= math.abs(arg.Z - slicedn24) and slicedn23 or slicedn24

						if flag4 < -440 or flag4 > -290 then
							flag4 = flag4 == slicedn23 and slicedn24 or slicedn23
						end

						local flag5 = math.abs(arg.X - slicedn17) <= math.abs(arg.X - slicedn18) and slicedn17 or slicedn18

						if math.abs(arg.Z - flag4) < 3 then
							flag5 = math.abs(arg2.X - slicedn17) <= math.abs(arg2.X - slicedn18) and slicedn17 or slicedn18
						end

						return Vector3.new(flag5, arg2.Y, flag4), sliced19.Name
					end
				end

				return arg2, nil
			end

			tbl4.SafeCarry.NewHuman = function(arg)
				local safeCarry = tbl4.SafeCarry
				local laneOffset = safeCarry.LaneOffset
				local tbl21

				tbl21 = {
					Clock = 0,
					Factor = 1,
					Target = 1,
					NextShift = 0,
					Phase = math.random() * 3.1415926535897931 * 2,
					Period = 2 + math.random() * 2.5,
					PauseUntil = 0,
					Lane = (math.random() * 2 - 1) * laneOffset,
					Step = function(arg2, arg3, arg4)
						tbl21.Clock = tbl21.Clock + arg2

						if tbl21.NextShift <= tbl21.Clock then
							tbl21.NextShift = tbl21.Clock + 0.5 + math.random()
							local slicedn17 = math.max(safeCarry.SpeedJitter, 0)

							if arg then
								tbl21.Target = 1 - math.random() * slicedn17
							else
								tbl21.Target = 1 + (math.random() * 2 - 1) * slicedn17
							end
						end

						tbl21.Factor = tbl21.Factor + (tbl21.Target - tbl21.Factor) * math.min(arg2 * 3, 1)
						local wobble = safeCarry.Wobble
						local slicedn17 = math.sin(tbl21.Clock * 2 * 3.1415926535897931 / tbl21.Period + tbl21.Phase) * wobble
						arg4 = arg4 and arg3 and safeCarry.JumpsPerMinute > 0

						if arg4 then
							local slicedn18 = safeCarry.JumpsPerMinute / 60 * arg2
							arg4 = math.random() < slicedn18
						end

						if arg4 then
							pcall(function()
								arg3.Jump = true
							end)
						end

						local flag3 = false

						if not arg then
							if tbl21.Clock < tbl21.PauseUntil then
								flag3 = true
							else
								local flag4 = safeCarry.PausesPerMinute > 0

								if flag4 then
									local slicedn18 = safeCarry.PausesPerMinute / 60 * arg2
									flag4 = math.random() < slicedn18
								end

								if flag4 then
									tbl21.PauseUntil = tbl21.Clock + 0.3 + math.random() * 0.9
									flag3 = true
								end
							end
						end

						return tbl21.Factor, tbl21.Lane + slicedn17, flag3
					end,
				}

				return tbl21
			end

			tbl4.SafeCarry.React = function(arg, arg2)
				local slicedn17 = math.max(0, math.min(arg, arg2))
				local slicedn18 = math.max(arg, arg2, 0)
				return slicedn17 + math.random() * (slicedn18 - slicedn17)
			end

			tbl4.SafeCarry.RunTo = function(arg, arg2)
				local safeCarry = tbl4.SafeCarry
				local position = typeof(arg.CFrame) == "CFrame" and arg.CFrame.Position or nil
				if not position then
					return false
				end
				slicedfn22()
				local character = localPlayer.Character
				local humanoid = character and character:FindFirstChildOfClass("Humanoid")

				if humanoid then
					humanoid.PlatformStand = false

					if character:FindFirstChildWhichIsA("Tool") then
						pcall(function()
							humanoid:UnequipTools()
						end)
					end
				end

				local sliced19 = safeCarry.NewHuman(false)
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("SeparationLine")
				local x = world and world:IsA("BasePart") and world.Position.X or 552
				local sliced20 = stealHome()
				local sliced21 = tbl4.Root()
				local str3 = "field"
				local z = sliced21 and sliced21.Position.Z or position.Z

				if sliced21 and sliced20 and sliced21.Position.X < x - 2 then
					local z2 = sliced20.Z

					if (Vector3.new(sliced21.Position.X, 0, sliced21.Position.Z) - Vector3.new(sliced20.X, 0, sliced20.Z)).Magnitude > 20 then
						str3 = "safe"
					end

					z = z2
				end

				local slicedn17 = math.clamp(z + sliced19.Lane, -425, -300)
				local slicedn18 = position.Y + 3
				-- Instant TP only: the way back from the base side is always on the ground, in run
				local runHeight = (str3 == "safe" and safeCarry.Teleport) and 0 or safeCarry.RunHeight

				local function slicedfn54(arg3)
					local sliced22 = tbl4.Root()
					local character2 = localPlayer.Character
					local flag3 = not sliced22 or not character2 or math.abs(sliced22.Position.Y - arg3) < 1

					if not flag3 then
						local snapLimit = safeCarry.SnapLimit
						flag3 = math.abs(sliced22.Position.Y - arg3) > snapLimit
					end

					if flag3 then
						return false
					end

					pcall(function()
						local rotation = sliced22.CFrame.Rotation
						character2:PivotTo(CFrame.new(Vector3.new(sliced22.Position.X, arg3, sliced22.Position.Z)) * rotation)
						sliced22.AssemblyLinearVelocity = Vector3.new(sliced22.AssemblyLinearVelocity.X, 0, sliced22.AssemblyLinearVelocity.Z)
					end)

					return true
				end

				local function slicedfn55()
					if runHeight <= 0.5 then
						return
					end
					slicedfn54(slicedn18 + runHeight)
				end

				-- Go Method Fly: TP into the Light Dark biome through the portal, come back out, then fly the rest at 110%
				local legSpeed = nil
				local portalNode = (workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS"))
				portalNode = portalNode and portalNode:FindFirstChild("Build")
				portalNode = portalNode and portalNode:FindFirstChild("FuseBiomeLanePortals")
				local startRoot = tbl4.Root()
				if str3 == "field" and (safeCarry.GoMethod or "Fly") == "Fly" and safeCarry.PortalRoute ~= false and portalNode and startRoot
					and Vector3.new(position.X - startRoot.Position.X, 0, position.Z - startRoot.Position.Z).Magnitude > 250 then
					local startCF = startRoot.CFrame
					local function boxOf(node)
						local lo, hi
						local parts = node:IsA("BasePart") and { node } or node:GetDescendants()
						for _, d in ipairs(parts) do
							if d:IsA("BasePart") then
								local p, half = d.Position, d.Size / 2
								lo = lo and Vector3.new(math.min(lo.X, p.X - half.X), math.min(lo.Y, p.Y - half.Y), math.min(lo.Z, p.Z - half.Z)) or p - half
								hi = hi and Vector3.new(math.max(hi.X, p.X + half.X), math.max(hi.Y, p.Y + half.Y), math.max(hi.Z, p.Z + half.Z)) or p + half
							end
						end
						return lo, hi
					end
					-- the folder holds several portals: the Light Dark one is the child closest to its measured centre
					local REF = Vector3.new(5572.6, 90.3, -435.7)
					local lo, hi
					local bestD = math.huge
					for _, child in ipairs(portalNode:GetChildren()) do
						local clo, chi = boxOf(child)
						if clo then
							local d = ((clo + chi) / 2 - REF).Magnitude
							if d < bestD then
								lo, hi, bestD = clo, chi, d
							end
						end
					end

					if lo and bestD < 60 then
						local spot, size = (lo + hi) / 2, hi - lo
						local function inBiome()
							local r = tbl4.Root()
							return r ~= nil and r.Position.Y > 5000
						end
						local function placeAt(p)
							local r = tbl4.Root()
							if r then
								pcall(function()
									r.CFrame = CFrame.new(p) * r.CFrame.Rotation
									r.AssemblyLinearVelocity = Vector3.zero
									r.AssemblyAngularVelocity = Vector3.zero
								end)
							end
						end
						local function jumpNow()
							local character = localPlayer.Character
							local hum = character and character:FindFirstChildOfClass("Humanoid")
							if hum then
								pcall(function()
									hum.Jump = true
									hum:ChangeState(Enum.HumanoidStateType.Jumping)
								end)
							end
						end

						local entered = inBiome()
						local since = os.clock()
						while not entered and os.clock() - since < 2.5 do
							placeAt(spot)
							RunService.Heartbeat:Wait()
							entered = inBiome()
						end

						local floorY = spot.Y - size.Y / 2 - 8.3
						for _ = 1, 6 do
							if entered then
								break
							end
							placeAt(Vector3.new(spot.X, floorY, spot.Z + 2))
							task.wait(0.15)
							jumpNow()
							local w = 0
							while w < 0.9 and not entered do
								w += RunService.Heartbeat:Wait()
								entered = inBiome()
							end
						end

						if not entered then
							local r = tbl4.Root()
							if r then
								pcall(function()
									r.CFrame = startCF
									r.AssemblyLinearVelocity = Vector3.zero
									r.AssemblyAngularVelocity = Vector3.zero
								end)
							end
							task.wait(0.2)
						end

						if entered then
							str2 = "Portal: in the biome"
							task.wait(0.6)
							local leaveSince = os.clock()
							while inBiome() and os.clock() - leaveSince < 9 do
								RunService.Heartbeat:Wait()
							end
							if inBiome() then
								str2 = "Portal: still in the biome"
								return false
							end
							if humanoid then
								pcall(function()
									humanoid.PlatformStand = false
								end)
							end
							legSpeed = 1.1
						end
					end
				end

				if str3 == "field" then
					slicedfn55()
				end

				local now = os.clock()
				local now2 = os.clock()
				local now3 = os.clock()
				local position2 = sliced21 and sliced21.Position or nil

				local function slicedfn56(arg3, arg4, arg5, arg6)
					local vector = Vector3.new(arg4.X - arg3.Position.X, 0, arg4.Z - arg3.Position.Z)
					local magnitude = vector.Magnitude
					local unit = magnitude > 0.01 and vector.Unit or Vector3.zero

					if runHeight > 0.5 and str3 == "field" and not arg6 then
						local runSpeed = safeCarry.Cap(legSpeed or safeCarry.RunSpeed)
						local slicedn19 = math.max(tbl4.WalkSpeed() * runSpeed * arg5, 8)
						local slicedn20 = math.clamp(safeCarry.ClimbShare, 0.1, 0.9)
						local magnitude2 = Vector3.new(position.X - arg3.Position.X, 0, position.Z - arg3.Position.Z).Magnitude

						if magnitude2 <= 3 then
							if slicedfn54(slicedn18) then
								return
							end
						end

						local slicedn21 = magnitude2 <= 3 and slicedn18 or slicedn18 + runHeight
						if math.abs(slicedn21 - arg3.Position.Y) > 2 and slicedfn54(slicedn21) then
							return
						end
						local slicedn22 = math.clamp((slicedn21 - arg3.Position.Y) / 0.12, -slicedn19 * slicedn20, slicedn19 * slicedn20)
						local slicedn23 = unit * math.min(math.sqrt(math.max(slicedn19 * slicedn19 - slicedn22 * slicedn22, 0)), magnitude / 0.05)

						pcall(function()
							arg3.AssemblyLinearVelocity = Vector3.new(slicedn23.X, slicedn22, slicedn23.Z)
						end)

						return
					end

					pcall(function()
						if arg6 or magnitude <= 0.01 then
							if humanoid then
								if safeCarry.RunStyle == "Walk" then
									humanoid:MoveTo(arg3.Position)
								end

								humanoid:Move(Vector3.zero, false)
							end

							if safeCarry.RunStyle ~= "Walk" then
								arg3.AssemblyLinearVelocity = Vector3.new(0, arg3.AssemblyLinearVelocity.Y, 0)
							end
						elseif safeCarry.RunStyle == "Walk" then
							if humanoid then
								humanoid:MoveTo(arg3.Position + unit * math.min(magnitude, 30))
							end
						else
							local runSpeed = safeCarry.Cap(legSpeed or safeCarry.RunSpeed)
							local slicedn19 = unit * math.min(math.max(tbl4.WalkSpeed() * runSpeed * arg5, 8), magnitude / 0.05)
							arg3.AssemblyLinearVelocity = Vector3.new(slicedn19.X, arg3.AssemblyLinearVelocity.Y, slicedn19.Z)

							if safeCarry.RunAnimate and humanoid then
								humanoid:Move(unit, false)
							end
						end
					end)
				end

				while os.clock() - now < 240 do
					if slicedfn13(arg2) then
						return false
					end
					local sliced22 = tbl4.Root()
					if not sliced22 then
						return false
					end
					local now4 = os.clock()
					local slicedn19 = math.max(now4 - now2, 0.0041666666666666666)
					local vector = Vector3.new(position.X - sliced22.Position.X, 0, position.Z - sliced22.Position.Z)
					if str3 == "field" and vector.Magnitude <= 2.5 and (runHeight <= 0.5 or sliced22.Position.Y - slicedn18 < 4) then
						break
					end
					local sliced23, sliced24, flag3 = sliced19.Step(slicedn19, humanoid, humanoid and humanoid.FloorMaterial ~= Enum.Material.Air)

					if vector.Magnitude <= 15 then
						flag3 = false
					end

					local vector2 = position

					if str3 == "safe" and sliced20 then
						if (Vector3.new(sliced20.X, 0, sliced20.Z) - Vector3.new(sliced22.Position.X, 0, sliced22.Position.Z)).Magnitude <= 6 then
							str3 = "field"
							slicedfn55()
						end

						str2 = "Walking out to the safe zone"
						vector2 = sliced20
					else
						if not safeCarry.StraightRun and runHeight <= 0.5 and math.abs(position.X - sliced22.Position.X) > 25 then
							vector2 = Vector3.new(position.X, position.Y, math.clamp(slicedn17 + sliced24, -425, -300))
						end

						str2 = string.format("Running to the egg, %d studs left", math.floor(vector.Magnitude + 0.5))
					end

					local sliced25, sliced26 = safeCarry.Avoid(sliced22.Position, vector2)

					if sliced26 then
						str2 = "Walking around " .. tostring(sliced26)
					end

					slicedfn56(sliced22, sliced25, sliced23, flag3)

					if now4 - now3 >= 1.5 then
						if not flag3 and position2 and (sliced22.Position - position2).Magnitude < 3 and humanoid then
							pcall(function()
								humanoid.Jump = true
							end)
						end

						position2 = sliced22.Position
						now3 = now4
					end

					RunService.Heartbeat:Wait()
					now2 = now4
				end

				local sliced22 = tbl4.Root()

				if sliced22 then
					slicedfn56(sliced22, sliced22.Position, 1, true)
				end

				local vector = nil

				if sliced22 then
					local vector2 = Vector3.new(sliced22.Position.X - position.X, 0, sliced22.Position.Z - position.Z)
					local vector3 = vector2.Magnitude > 0.1 and vector2.Unit * 2 or Vector3.zero
					vector = Vector3.new(position.X + vector3.X, sliced22.Position.Y, position.Z + vector3.Z)
				end

				local connection = RunService.Heartbeat:Connect(function()
					local sliced23 = tbl4.Root()
					if not sliced23 or not vector or tbl4.Steal.Carrying or tbl4.AntiGuard.Busy then
						return
					end
					local vector2 = Vector3.new(vector.X - sliced23.Position.X, 0, vector.Z - sliced23.Position.Z)

					pcall(function()
						if vector2.Magnitude > 1.5 then
							local rotation = sliced23.CFrame.Rotation
							sliced23.CFrame = CFrame.new(vector.X, sliced23.Position.Y, vector.Z) * rotation
						end

						sliced23.AssemblyLinearVelocity = Vector3.new(0, math.min(sliced23.AssemblyLinearVelocity.Y, 0), 0)
					end)
				end)

				local function slicedfn57(arg3)
					connection:Disconnect()
					return arg3
				end

				local sliced23 = slicedfn41(arg)
				local now4 = os.clock()
				local sliced24 = safeCarry.React(safeCarry.ReactMin, safeCarry.ReactMax)

				while true do
					if slicedfn13(arg2) then
						return (slicedfn57(false))
					else
						local slicedn19 = os.clock() - now4
						local slicedn20 = safeCarry.RunWait + sliced24
						local flag3 = not safeCarry.WaitGuard or not sliced23 or sliced23:GetAttribute("GuardState") == "Sleeping"
						if slicedn19 >= slicedn20 and (flag3 or slicedn19 >= slicedn20 + 15) then
							break
						end
						str2 = slicedn19 < slicedn20 and string.format("Waiting before the grab, %.1fs", slicedn20 - slicedn19) or "Waiting for the guard to sleep"
						RunService.Heartbeat:Wait()
					end
				end

				str2 = "Taking the egg"
				local sliced25 = slicedfn44(arg, arg2, 0.8, nil)

				if not sliced25 and not slicedfn13(arg2) then
					sliced25 = slicedfn30(arg, arg2)
				end

				slicedfn57()
				if not sliced25 then
					return false
				end
				tbl4.Steal.LastFinishedAt = os.clock()
				return true
			end

			tbl4.SafeCarry.Pace = function()
				local slicedn17 = tonumber(tbl4.SafeCarry.RunSpeed) or 1
				slicedn17 = tbl4.SafeCarry.Cap(slicedn17)
				return math.max(tbl4.WalkSpeed() * slicedn17, 16)
			end

			tbl4.SafeCarry.Plan = function(arg, arg2, arg3)
				local safeCarry = tbl4.SafeCarry
				local character = localPlayer.Character

				if character then
					character:FindFirstChildOfClass("Humanoid")
				end

				local sliced19 = tbl4.WalkSpeed()
				arg3 = arg3 or safeCarry.Mult or 1

				if safeCarry.SameSpeedBigEggs then
					arg3 = math.max(arg3, safeCarry.LightMult)
				end

				local slicedn17 = sliced19 * safeCarry.Cap(safeCarry.CarryRatio) * arg3
				local slicedn18 = slicedn17 * safeCarry.SpeedRatio
				local slicedn19 = safeCarry.ExcessSeconds * slicedn17
				local slicedn20

				if arg2 and arg2 > slicedn19 then
					slicedn20 = math.min(slicedn18, slicedn17 * arg2 / (arg2 - slicedn19))
				else
					slicedn20 = slicedn18
				end

				local guards = tbl.Guards
				local flag3 = type(guards) == "table" and type(guards.Directory) == "table" and guards.Directory[tostring(arg)] or nil
				local slicedn21 = type(flag3) == "table" and tonumber(flag3.WalkSpeed) or 0

				if not safeCarry.BeatGuard then
					return math.min(math.max(math.min(slicedn17 * safeCarry.EasyRatio, slicedn20), slicedn17), math.max(sliced19 * 1.15, slicedn17)), true, slicedn17, slicedn20, slicedn21
				end
				local slicedn22 = math.max(slicedn21 + safeCarry.GuardMargin, slicedn17 * safeCarry.MinRatio)
				local slicedn23 = math.max(slicedn22, slicedn21 * safeCarry.GuardRatio)

				if slicedn20 < slicedn22 then
					local slicedn24 = slicedn17 * safeCarry.SpeedRatio
					local slicedn25 = safeCarry.StretchSeconds * slicedn17
					local slicedn26

					if arg2 and arg2 > slicedn25 then
						slicedn26 = math.min(slicedn24, slicedn17 * arg2 / (arg2 - slicedn25))
					else
						slicedn26 = slicedn24
					end

					local slicedn27 = slicedn21 + math.max(safeCarry.GuardMargin, 1)
					if slicedn27 <= slicedn26 then
						return slicedn27, true, slicedn17, slicedn26, slicedn21
					end
				end

				return math.max(math.min(slicedn23, slicedn20), slicedn17), slicedn22 <= slicedn20, slicedn17, slicedn20, slicedn21
			end

			tbl4.SafeCarry.Unsafe = function(arg)
				local safeCarry = tbl4.SafeCarry
				if not safeCarry.Enabled or type(arg) ~= "table" or not arg.Uid or not safeCarry.Blocked[arg.Uid] then
					return nil
				end
				return string.format("the guard caught you with this %s before, skipping it", tostring(arg.Category))
			end

			tbl4.SafeCarry.Settle = function(arg, arg2)
				local safeCarry = tbl4.SafeCarry
				local character = localPlayer.Character

				if character then
					character:FindFirstChildOfClass("Humanoid")
				end

				math.max(tbl4.WalkSpeed() * safeCarry.CarryRatio * (safeCarry.Seen[tostring(arg2.Category)] or safeCarry.GuessMult) * safeCarry.WaitRate, 1)
				local baseWait = safeCarry.BaseWait
				local sliced19 = slicedfn41(arg2)

				while true do
					if slicedfn13(arg) then
						return false
					else
						local slicedn17 = os.clock() - (safeCarry.JumpAt or 0)
						local flag3 = not safeCarry.WaitGuard or not sliced19 or sliced19:GetAttribute("GuardState") == "Sleeping"
						if slicedn17 >= baseWait and (flag3 or slicedn17 >= baseWait + 15) then
							break
						end

						if slicedn17 < baseWait then
							str2 = string.format("Letting the jump settle, %.1fs", baseWait - slicedn17)
						else
							str2 = "Waiting for the guard to sleep"
						end

						RunService.Heartbeat:Wait()
					end
				end

				return true
			end

			tbl4.MonitorAction = tbl4.MonitorAction or function(arg)
				local ok, result = pcall(debug.getconstants, arg)
				if not ok or type(result) ~= "table" then
					return false
				end

				for _, sliced19 in pairs(result) do
					local flag3 = type(sliced19) == "string"

					if flag3 then
						flag3 = sliced19 == "Relocate" or sliced19 == "SetWalkSpeed" or sliced19 == "BeginRagdoll" or sliced19 == "EndRagdoll" or sliced19 == "BeginImpulse"
					end

					if flag3 then
						return true
					end
				end

				return false
			end

			-- Instant TP without Anti Guard: the server let go of the egg on the way. Take it straight back,
			-- teleporting onto it when it is far and running to it when it is close
			tbl4.SafeCarry.Regrab = function(arg, uid, force)
				local sc = tbl4.SafeCarry

				if tbl4.Steal.Carrying then
					return true
				end

				if not sc.Teleport or (tbl4.AntiGuard.Enabled and not force) then
					return false
				end

				local eggPos = slicedfn48(uid or tbl4.Steal.CarryUid)
				local root = tbl4.Root()

				if eggPos and root and Vector3.new(root.Position.X - eggPos.X, 0, root.Position.Z - eggPos.Z).Magnitude > 40 then
					str2 = "Instant TP: the egg fell far behind, teleporting onto it"
					pcall(function()
						root.CFrame = CFrame.new(eggPos + Vector3.new(0, 3, 0)) * CFrame.Angles(0, 1.5707963267948966, 0)
						root.AssemblyLinearVelocity = Vector3.zero
						root.AssemblyAngularVelocity = Vector3.zero
					end)
				else
					str2 = "Instant TP: the egg fell close, running back to it"
				end

				return slicedfn50(arg, uid) and tbl4.Steal.Carrying and not tbl4.Steal.WrongEgg(uid or tbl4.Steal.CarryUid)
			end

			tbl4.SafeCarry.LineDropHome = function(arg)
				if SourcesLib.ReleaseCamera then pcall(SourcesLib.ReleaseCamera) end
				local safeCarry = tbl4.SafeCarry
				local steal = tbl4.Steal
				local carryUid = steal.CarryUid
				local sliced19 = stealHome()
				local sliced20 = tbl4.Root()
				if type(carryUid) ~= "string" or not sliced19 or not sliced20 then
					return false
				end
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("SeparationLine")
				local x = world and world:IsA("BasePart") and world.Position.X or 552.2
				local y = world and world:IsA("BasePart") and world.Position.Y or 67.67
				local tbl21 = {}

				pcall(function()
					for _, sliced21 in ipairs({ RunService.Heartbeat, RunService.PreSimulation, RunService.PostSimulation }) do
						for _, sliced22 in ipairs(getconnections(sliced21)) do
							local ok, result = pcall(function()
								return sliced22.Function
							end)

							if ok and type(result) == "function" then
								local ok2, result2 = pcall(debug.info, result, "s")

								if ok2 and string.find(tostring(result2), "UGI", 1, true) and not tbl4.MonitorAction(result) then
									local ok3, result3 = pcall(function()
										return sliced22.Enabled
									end)

									if not ok3 or result3 ~= false then
										if pcall(function()
											sliced22:Disable()
										end) then
											table.insert(tbl21, sliced22)
										end
									end
								end
							end
						end
					end
				end)

				local flag3 = false
				local connection = nil

				pcall(function()
					connection = networking["RE/RigSync/Refresh"].OnClientEvent:Connect(function(arg2)
						if type(arg2) == "table" and arg2.Action == "Relocate" then
							flag3 = true
						end
					end)
				end)

				local currentCamera = workspace.CurrentCamera
				local tbl22 = nil

				local function slicedfn54()
					if tbl22 or not currentCamera or safeCarry.StopMode then
						return
					end
					tbl22 = { Type = currentCamera.CameraType, CFrame = currentCamera.CFrame }
					tbl4.CameraFrozen = tbl22.Type

					pcall(function()
						currentCamera.CameraType = Enum.CameraType.Scriptable
						currentCamera.CFrame = tbl22.CFrame
					end)
				end

				local function slicedfn55()
					if not tbl22 or not currentCamera then
						return
					end
					local sliced21 = tbl22
					tbl22 = nil
					tbl4.CameraFrozen = nil

					pcall(function()
						currentCamera.CameraType = sliced21.Type
					end)
				end

				local function slicedfn56()
					slicedfn55()
					pcall(tbl4.CarryCap.Off)
					pcall(tbl4.DropClone)

					if connection then
						connection:Disconnect()
						connection = nil
					end

					for _, sliced21 in ipairs(tbl21) do
						pcall(function()
							sliced21:Enable()
						end)
					end

					table.clear(tbl21)
				end

				local now = os.clock()

				local function slicedfn57(arg2, arg3, arg4, arg5)
					local slicedn17 = 0

					while slicedn17 < arg4 and not slicedfn13(arg) do
						local sliced21 = tbl4.Root()
						if not sliced21 then
							return false
						end

						if arg5 and arg5() then
							return true
						end
						local vector = Vector3.new(arg2.X - sliced21.Position.X, 0, arg2.Z - sliced21.Position.Z)
						if vector.Magnitude < 2.5 then
							return true
						end
						local slicedn18 = vector.Unit * math.min(arg3, vector.Magnitude / 0.05)

						pcall(function()
							sliced21.AssemblyLinearVelocity = Vector3.new(slicedn18.X, sliced21.AssemblyLinearVelocity.Y, slicedn18.Z)
						end)

						slicedn17 += RunService.Heartbeat:Wait()
					end

					return false
				end

				slicedfn22()
				local slicedn17 = math.clamp(sliced20.Position.Z, -425, -300)
				local vector = Vector3.new(x + (safeCarry.Hops and safeCarry.HopStop or safeCarry.LineGap), y + 3.35, slicedn17)
				
				-- same arrival as Normal mode: first the checkpoint 7 studs past the line, then the base
				local crossCheckpoint = Vector3.new(x - 7, sliced19.Y, slicedn17)
				local function crossLine(ratio, stopFn)
					slicedfn57(crossCheckpoint, tbl4.WalkSpeed() * ratio, 6, stopFn)

					if steal.Carrying and safeCarry.LastDelivered < now and not slicedfn13(arg) then
						slicedfn57(sliced19, tbl4.WalkSpeed() * ratio, 6, stopFn)
					end
				end

				-- Anti Guard already put us in the safe zone (past the line): do not jump back in front of it
				if sliced20.Position.X < x - 2 then
					str2 = "Already in the safe zone"

					if not steal.Carrying then
						slicedfn50(arg, carryUid)
					end

					if steal.Carrying then
						tbl4.ClearClones()
					end

					if steal.Carrying and safeCarry.LastDelivered < now and not slicedfn13(arg) then
						crossLine(safeCarry.Cap(safeCarry.CrossRatio), function()
							return safeCarry.LastDelivered >= now or not steal.Carrying
						end)
					end
					local settle = 0

					while settle < 2 and safeCarry.LastDelivered < now and steal.Carrying and not slicedfn13(arg) do
						settle += RunService.Heartbeat:Wait()
					end
					slicedfn56()
					return safeCarry.LastDelivered >= now
				end



				local function slicedfn58()
					local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")

					local ok, result = pcall(function()
						return rfEggWorldAskFieldEggSnapshot:InvokeServer()
					end)

					local records = ok and type(result) == "table" and result.Records or nil

					if type(records) == "table" then
						for _, record in pairs(records) do
							if type(record) == "table" and record.Uid == carryUid then
								return record
							end
						end
					end

					return nil
				end

				local magnitude = Vector3.new(sliced20.Position.X - x, 0, sliced20.Position.Z - slicedn17).Magnitude
				local max = math.max
				local carryRatio = safeCarry.Cap(safeCarry.CarryRatio)
				local sliced21 = max(tbl4.WalkSpeed() * carryRatio * (tonumber(safeCarry.Mult) or safeCarry.LightMult), 1)
				local directMargin = safeCarry.DirectMargin
				local slicedn18 = math.max(0, (magnitude - safeCarry.DirectBudget) / sliced21) + directMargin

				if safeCarry.CrossNow then
					slicedn18 = safeCarry.DirectMargin
				end

				local function slicedfn59()
					local sliced22 = tbl4.Root()
					if not sliced22 then
						return
					end

					-- Instant TP: never jump backwards, if we are already closer to the line than the landing spot, stay
					if safeCarry.Teleport and sliced22.Position.X <= vector.X + 1 and sliced22.Position.Y > vector.Y - 25 then
						pcall(function()
							sliced22.AssemblyLinearVelocity = Vector3.zero
						end)
						return
					end

					pcall(function()
						sliced22.CFrame = CFrame.new(vector) * CFrame.Angles(0, 1.5707963267948966, 0)
						sliced22.AssemblyLinearVelocity = Vector3.zero
						sliced22.AssemblyAngularVelocity = Vector3.zero
					end)
				end

				slicedfn54()

				if safeCarry.Hops then
					local sliced22 = tbl4.Root()

					if sliced22 then
						local slicedn19 = sliced22.Position.Y + safeCarry.HopLift
						local x2 = sliced22.Position.X
						local hopRatio = safeCarry.HopRatio
						local slicedn20 = math.max(tbl4.WalkSpeed() * hopRatio, 40)
						local hopStartX = x2
						local hopStops = 0
						local hopRetries = 0
						local lastImpulse = tbl4.Analyzer.ImpulseAt
						local function eggAtNest()
							local record = slicedfn58()
							return record ~= nil and record.State == "Slot"
						end
						local hopStopsWanted = safeCarry.StopMode and not safeCarry.Straight and math.clamp(math.floor(tonumber(safeCarry.Stops) or 3) - 1, 0, 5) or 0

						-- a clone stays where the egg was taken, the lag starts here
						pcall(tbl4.PostClone)

						if not (safeCarry.Teleport and safeCarry.TpFpsCap == false) then
							pcall(tbl4.CarryCap.On)
						end


						local midRegrabs = 0

						while x2 - slicedn20 > vector.X and (steal.Carrying or (safeCarry.Teleport and not safeCarry.StopMode and midRegrabs < 4 and not slicedfn13(arg) and (function()
							midRegrabs += 1
							local regrabbed = tbl4.SafeCarry.Regrab(arg, carryUid)
							local regrabRoot = tbl4.Root()

							if regrabbed and regrabRoot then
								x2 = math.min(x2, regrabRoot.Position.X)
							end

							return regrabbed
						end)())) and not slicedfn13(arg) do
							x2 -= slicedn20
							tbl4.Trip = { Phase = "Hopping", Progress = (hopStartX - x2) / math.max(hopStartX - vector.X, 1), Stop = hopStops + 1, Stops = hopStopsWanted + 1, At = os.clock() }
							pcall(tbl4.Analyzer.Event, "hop", string.format("x=%.0f", x2))
							str2 = string.format("Line Drop: hopping home, X %d", math.floor(x2))
							local slicedn21 = 0

							while slicedn21 < safeCarry.HopGap do
								local sliced23 = tbl4.Root()

								if sliced23 then
									pcall(function()
										sliced23.CFrame = CFrame.new(x2, slicedn19, slicedn17) * CFrame.Angles(0, 1.5707963267948966, 0)
										sliced23.AssemblyLinearVelocity = Vector3.zero
										sliced23.AssemblyAngularVelocity = Vector3.zero
									end)
								end

								slicedn21 += RunService.Heartbeat:Wait()
							end

							-- failure detection: the server pulled us back (Relocate) or the body is far behind the hop target
							local checkRoot = tbl4.Root()
							local impulsed = tbl4.Analyzer.ImpulseAt > lastImpulse
							lastImpulse = math.max(lastImpulse, tbl4.Analyzer.ImpulseAt)
							local tooFast = checkRoot ~= nil and checkRoot.AssemblyLinearVelocity.Magnitude > 150
							local pulledBack = flag3 or impulsed or tooFast or (checkRoot ~= nil and checkRoot.Position.X - x2 > 10)

							if pulledBack and steal.Carrying and not slicedfn13(arg) then
								flag3 = false
								if eggAtNest() then
									slicedfn56()
									str2 = "Delivery Stop: the egg went back to its nest, stopping"
									pcall(tbl4.Analyzer.Event, "nest", "egg back at its origin")
									return false
								end
								hopRetries += 1
								pcall(tbl4.Analyzer.Event, "pullback", string.format("retry %d at x=%.0f", hopRetries, x2))

								if hopRetries <= 6 then
									str2 = string.format("Delivery Stop: pulled back, retry %d/6", hopRetries)
									tbl4.Trip = { Phase = "Hopping", Progress = (hopStartX - x2) / math.max(hopStartX - vector.X, 1), Stop = hopStops + 1, Stops = hopStopsWanted + 1, At = os.clock() }
									local settleT = 0

									while settleT < 0.25 and not slicedfn13(arg) do
										settleT += RunService.Heartbeat:Wait()
									end

									local realRoot = tbl4.Root()

									if realRoot then
										x2 = math.min(realRoot.Position.X, hopStartX)
									end
									
									continue
								else
									str2 = "Delivery Stop: pulled back too often, finishing from here"
								end
							end

							if hopStops < hopStopsWanted and (hopStartX - x2) / math.max(hopStartX - vector.X, 1) >= (hopStops + 1) / (hopStopsWanted + 1) then
								hopStops += 1
								str2 = string.format("Delivery step %d/%d", hopStops, hopStopsWanted + 1)
								pcall(tbl4.Analyzer.Event, "step", string.format("%d/%d at x=%.0f", hopStops, hopStopsWanted + 1, x2))

								local function tripStop()
									tbl4.Trip = { Phase = "Stop", Progress = (hopStartX - x2) / math.max(hopStartX - vector.X, 1), Stop = hopStops, Stops = hopStopsWanted + 1, At = os.clock() }
								end

								tripStop()
								local stepRoot = tbl4.Root()
								local ground = nil

								if stepRoot then
									local params = RaycastParams.new()
									params.FilterType = Enum.RaycastFilterType.Exclude
									params.FilterDescendantsInstances = { localPlayer.Character, tbl4.StealClone }
									params.IgnoreWater = true
									local hit = workspace:Raycast(Vector3.new(x2, slicedn19 + 5, slicedn17), Vector3.new(0, -400, 0), params)

									if hit and hit.Material ~= Enum.Material.Water then
										ground = hit.Position
									end
								end

								pcall(tbl4.Analyzer.Event, "ground", ground ~= nil and string.format("y=%.1f", ground.Y) or "none")

								if ground and carryUid then
									-- go down to the ground, drop the egg, take it back, climb back to the lane
									pcall(function()
										stepRoot.CFrame = CFrame.new(ground + Vector3.new(0, 3.5, 0)) * CFrame.Angles(0, 1.5707963267948966, 0)
										stepRoot.AssemblyLinearVelocity = Vector3.zero
										stepRoot.AssemblyAngularVelocity = Vector3.zero
									end)

									local settle = 0

									while settle < 0.12 and not slicedfn13(arg) do
										settle += RunService.Heartbeat:Wait()
										tripStop()
									end

									str2 = string.format("Delivery step %d/%d: dropping the egg", hopStops, hopStopsWanted + 1)
									local eggState = tbl.EggState

									if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
										pcall(eggState.DropFieldEgg, "PlayerRequest")
									end

									local dropWait = 0

									while steal.Carrying and dropWait < 1 and not slicedfn13(arg) do
										dropWait += RunService.Heartbeat:Wait()
										tripStop()
									end

									if not steal.Carrying and eggAtNest() then
										slicedfn56()
										str2 = "Delivery Stop: the egg went back to its nest, stopping"
										return false
									end

									if not steal.Carrying then
										str2 = string.format("Delivery step %d/%d: taking the egg back", hopStops, hopStopsWanted + 1)
										tripStop()

										if not slicedfn50(arg, carryUid) or not steal.Carrying then
											slicedfn56()
											str2 = "Delivery Stop: could not take the egg back"
											return false
										end
									end

									local backRoot = tbl4.Root()

									if backRoot then
										pcall(function()
											backRoot.CFrame = CFrame.new(x2, slicedn19, slicedn17) * CFrame.Angles(0, 1.5707963267948966, 0)
											backRoot.AssemblyLinearVelocity = Vector3.zero
											backRoot.AssemblyAngularVelocity = Vector3.zero
										end)
									end
								else
									-- nothing solid below (water / void): only a short pause, the egg is not dropped here
									local held = 0

									while held < 0.3 and steal.Carrying and not slicedfn13(arg) do
										local stopRoot = tbl4.Root()

										if stopRoot then
											pcall(function()
												stopRoot.CFrame = CFrame.new(x2, slicedn19, slicedn17) * CFrame.Angles(0, 1.5707963267948966, 0)
												stopRoot.AssemblyLinearVelocity = Vector3.zero
												stopRoot.AssemblyAngularVelocity = Vector3.zero
											end)
										end

										held += RunService.Heartbeat:Wait()
										tripStop()
									end
								end
							end
						end
					end
				end

				if safeCarry.StopMode and not steal.Carrying then
					local nestRecord = slicedfn58()

					if nestRecord and nestRecord.State == "Slot" then
						slicedfn56()
						str2 = "Delivery Stop: the egg went back to its nest, stopping"
						return false
					end
				end

				str2 = "Line Drop: landing next to the line"

				pcall(function()
					local params = RaycastParams.new()
					params.FilterType = Enum.RaycastFilterType.Exclude
					params.FilterDescendantsInstances = { localPlayer.Character, tbl4.StealClone }
					params.IgnoreWater = true
					local hit = workspace:Raycast(vector + Vector3.new(0, 60, 0), Vector3.new(0, -140, 0), params)

					if hit and hit.Material ~= Enum.Material.Water and math.abs(hit.Position.Y - vector.Y) < 40 then
						vector = Vector3.new(vector.X, hit.Position.Y + 3.5, vector.Z)
					end
				end)

				slicedfn59()

				for attempt = 1, 3 do
					local settle = 0

					while settle < (safeCarry.Teleport and 0.08 or 0.15) and not slicedfn13(arg) do
						settle += RunService.Heartbeat:Wait()
					end
					local landed = tbl4.Root()

					if steal.Carrying and landed and ((safeCarry.Teleport and landed.Position.X - vector.X > 12) or (not safeCarry.Teleport and Vector3.new(landed.Position.X - vector.X, 0, landed.Position.Z - vector.Z).Magnitude > 12) or landed.Position.Y < vector.Y - 25) then
						str2 = "Line Drop: landing retry " .. attempt
						slicedfn59()
					else
						break
					end
				end

				if safeCarry.Teleport then
					-- arrived in front of the line: no copy of us may stay behind
					tbl4.ClearClones()
				end

				if safeCarry.Hops and steal.Carrying then
					local slicedn19 = 0

					while slicedn19 < (safeCarry.Teleport and 0.05 or safeCarry.DropDelay) and steal.Carrying and not slicedfn13(arg) do
						slicedn19 += RunService.Heartbeat:Wait()
					end

					if steal.Carrying then
						str2 = "Line Drop: dropping the egg next to the line"
						local eggState = tbl.EggState

						if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
							pcall(eggState.DropFieldEgg, "PlayerRequest")
						end

						local slicedn20 = 0

												while steal.Carrying and slicedn20 < 1 and not slicedfn13(arg) do
							slicedn20 += RunService.Heartbeat:Wait()
						end

						-- Instant TP: egg is down -> let go of everything (camera, clones, speed) and force the grab right away
						if safeCarry.Teleport and not steal.Carrying then
							slicedfn55()
							tbl4.ClearClones()
							str2 = "Instant TP: egg down, forcing the grab"
							local dropRoot = tbl4.Root()

							if dropRoot then
								pcall(function()
									dropRoot.AssemblyLinearVelocity = Vector3.zero
									dropRoot.AssemblyAngularVelocity = Vector3.zero
								end)
							end
							slicedfn50(arg, carryUid)

							if steal.Carrying then
								tbl4.ClearClones()

								-- no Anti Guard: egg is back in the hands, go straight to the safe zone (line checkpoint, then home)
								if not tbl4.AntiGuard.Enabled then
									slicedfn56()
									str2 = "Instant TP: egg retaken, heading to the safe zone"
									return tbl4.SafeCarry.Home(arg)
								end
							end
						end
					end
				end

				slicedfn55()

				if safeCarry.ShakeTime > 0 then
					local vector2 = Vector3.new(x - safeCarry.ShakeInside, vector.Y, slicedn17)
					local flag4 = false
					local slicedn19 = 0

					while slicedn19 < safeCarry.ShakeTime and steal.Carrying and not slicedfn13(arg) do
						str2 = "Line Drop: shaking at the line"
						flag4 = not flag4
						local sliced22 = tbl4.Root()

						if sliced22 then
							pcall(function()
								sliced22.CFrame = CFrame.new(flag4 and vector2 or vector) * CFrame.Angles(0, 1.5707963267948966, 0)
								sliced22.AssemblyLinearVelocity = Vector3.zero
							end)
						end

						slicedn19 += RunService.Heartbeat:Wait()
					end

					slicedfn59()
				end

				local flag4 = slicedn18 < safeCarry.LineWait
				local slicedn19 = 0
				local slicedn20 = 1

				while true do
					local flag5 = steal.Carrying and slicedn19 < safeCarry.LineWait

					if flag5 then
						flag5 = not (flag4 and slicedn19 >= slicedn18)
					end

					if flag5 and not slicedfn13(arg) then
						if flag4 then
							str2 = string.format("Line Drop: stepping over the line in %.1fs", math.max(slicedn18 - slicedn19, 0))
						else
							str2 = string.format("Line Drop: crossing needs %.1fs, waiting for the guard, %.0fs left", slicedn18, safeCarry.LineWait - slicedn19)
						end

						if flag3 and safeCarry.ReJump and slicedn20 < 40 and not slicedfn31() then
							flag3 = false
							slicedn20 += 1
							str2 = "Line Drop: pulled back, jumping to the line again"
							slicedfn59()
						end

						slicedn19 += RunService.Heartbeat:Wait()
						continue
					end

					break
				end

				if steal.Carrying and flag4 and slicedn19 >= slicedn18 and not slicedfn13(arg) then
					str2 = "Line Drop: stepping over the line"
					local crossRatio = safeCarry.Cap(safeCarry.CrossRatio)

					crossLine(crossRatio, function()
						return safeCarry.LastDelivered >= now or not steal.Carrying
					end)

					local slicedn21 = 0

					while slicedn21 < 1.5 and safeCarry.LastDelivered < now and steal.Carrying and not slicedfn13(arg) do
						slicedn21 += RunService.Heartbeat:Wait()
					end

					if safeCarry.LastDelivered >= now then
						slicedfn56()
						return true
					end
				end

				if steal.Carrying then
					slicedfn56()
					str2 = "Line Drop: the guard never came, dropping the egg"
					local eggState = tbl.EggState

					if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
						pcall(eggState.DropFieldEgg, "PlayerRequest")
					end

					return false
				end

				if safeCarry.GetUp then
					task.spawn(function()
						local slicedn21 = 0

						while slicedn21 < 1.5 do
							local character = localPlayer.Character
							local humanoid = character and character:FindFirstChildOfClass("Humanoid")

							if humanoid then
								pcall(function()
									humanoid.PlatformStand = false
									local state = humanoid:GetState()

									if state == Enum.HumanoidStateType.Physics or state == Enum.HumanoidStateType.Ragdoll or state == Enum.HumanoidStateType.FallingDown then
										humanoid:ChangeState(Enum.HumanoidStateType.GettingUp)
									end
								end)
							end

							slicedn21 += RunService.Heartbeat:Wait()
						end
					end)
				end

				local slicedn21 = 0

				while not safeCarry.SnapPickup and not safeCarry.GetUp and slicedfn31() and slicedn21 < 6 and not slicedfn13(arg) do
					str2 = "Line Drop: egg is down at the line, getting up"
					slicedn21 += RunService.Heartbeat:Wait()
				end

				local slicedn22 = 0

				while not slicedfn13(arg) and slicedn22 < 6 do
					slicedn22 += 1
					local sliced22 = slicedfn48(carryUid)

					if not sliced22 then
						slicedfn56()
						str2 = "Line Drop: the egg is gone"
						return false
					end

					local sliced23 = slicedfn58()

					if sliced23 and sliced23.State == "Slot" then
						slicedfn56()
						str2 = "Line Drop: the egg went back to its nest"
						return false
					end

					str2 = "Line Drop: picking the egg up at the line"

					if safeCarry.Teleport then
						str2 = "Instant TP: taking the egg back"

						if slicedfn50(arg, carryUid) and steal.Carrying then
							break
						end
					end
					local slicedn23

					if safeCarry.SnapPickup then
						local sliced24 = tbl4.Root()

						if sliced24 then
							pcall(function()
								sliced24.CFrame = CFrame.new(sliced22 + Vector3.new(0, 3, 0)) * CFrame.Angles(0, 1.5707963267948966, 0)
								sliced24.AssemblyLinearVelocity = Vector3.zero
							end)
						end

						slicedn23 = 5
					else
						local pickupRatio = safeCarry.Cap(safeCarry.PickupRatio)
						slicedfn57(sliced22, tbl4.WalkSpeed() * pickupRatio, 5)
						slicedn23 = 2.5
					end

					local slicedn24 = 0

					while not steal.Carrying and slicedn24 < slicedn23 and not slicedfn13(arg) do
						-- Instant TP: if the server pulled us back while retaking the egg, go straight back to where it lies
						if safeCarry.Teleport and flag3 then
							flag3 = false
							sliced22 = slicedfn48(carryUid) or sliced22
							local backRoot = tbl4.Root()

							if backRoot then
								str2 = "Instant TP: pulled back, returning to the egg"
								pcall(function()
									backRoot.CFrame = CFrame.new(sliced22 + Vector3.new(0, 3, 0)) * CFrame.Angles(0, 1.5707963267948966, 0)
									backRoot.AssemblyLinearVelocity = Vector3.zero
								end)
							end
						end

						task.spawn(slicedfn28, carryUid)

						if safeCarry.SnapPickup then
							local sliced24 = tbl4.Root()
							sliced22 = slicedfn48(carryUid) or sliced22

							if sliced24 and Vector3.new(sliced24.Position.X - sliced22.X, 0, sliced24.Position.Z - sliced22.Z).Magnitude > 3 then
								pcall(function()
									sliced24.CFrame = CFrame.new(sliced22 + Vector3.new(0, 3, 0)) * CFrame.Angles(0, 1.5707963267948966, 0)
									sliced24.AssemblyLinearVelocity = Vector3.zero
								end)
							end
						end

						slicedn24 += task.wait((safeCarry.SnapPickup or safeCarry.Teleport) and 0.08 or 0.15)
					end

					if steal.Carrying and not steal.WrongEgg(carryUid) then
						if safeCarry.Teleport then
							tbl4.ClearClones()
						end
						break
					end
				end

				if not steal.Carrying then
					slicedfn56()
					str2 = "Line Drop: could not pick the egg up again"
					return false
				end

				local sliced22 = tbl4.Root()

				if sliced22 and sliced22.Position.X - x > safeCarry.FarFromLine then
					slicedfn56()
					str2 = "Line Drop: egg ended up far from the line, carrying it home safely"
					return tbl4.SafeCarry.Home(arg)
				end

				if safeCarry.Teleport and not tbl4.AntiGuard.Enabled then
					slicedfn56()
					return tbl4.SafeCarry.Home(arg)
				end

				str2 = "Line Drop: stepping over the line"
				local crossRatio = safeCarry.Cap(safeCarry.CrossRatio)

				crossLine(crossRatio, function()
					return safeCarry.LastDelivered >= now or not steal.Carrying
				end)

				local sliced23 = tbl4.Root()

				if sliced23 then
					pcall(function()
						sliced23.AssemblyLinearVelocity = Vector3.new(0, sliced23.AssemblyLinearVelocity.Y, 0)
					end)
				end

				local slicedn23 = 0

				while slicedn23 < 2 and safeCarry.LastDelivered < now and steal.Carrying and not slicedfn13(arg) do
					slicedn23 += RunService.Heartbeat:Wait()
				end

				slicedfn56()
				return safeCarry.LastDelivered >= now
			end

			tbl4.SafeCarry.Home = function(arg)
				local safeCarry = tbl4.SafeCarry
				local sliced19 = stealHome()
				local sliced20 = tbl4.Root()
				if not sliced19 or not sliced20 then
					return false
				end
				slicedfn22()
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("SeparationLine")
				local slicedn17 = (world and world:IsA("BasePart") and world.Position.X or 552) - 7
				local character = localPlayer.Character
				local humanoid = character and character:FindFirstChildOfClass("Humanoid")

				if humanoid then
					humanoid.PlatformStand = false
				end

				local now = os.clock()
				local slicedn18 = 0

				local function slicedfn54()
					local sliced21 = tbl4.Root()
					if not sliced21 then
						return
					end
					local sliced22, sliced23, sliced24, sliced25, sliced26 = safeCarry.Plan(tbl4.Steal.CarryAreaId, (Vector3.new(sliced21.Position.X, 0, sliced21.Position.Z) - Vector3.new(sliced19.X, 0, sliced19.Z)).Magnitude + math.max(0, safeCarry.Height) * 2, safeCarry.Mult)
					local slicedn19 = sliced22 * safeCarry.CarryScale
					slicedn18 = slicedn19
					safeCarry.PlanOk = sliced23
					safeCarry.FloorSpeed = safeCarry.BeatGuard and math.min(sliced26 + math.max(safeCarry.GuardMargin, 1), sliced25) or 0
					str2 = string.format("Carrying home at %d (carry %d, guard %d, max %d)%s", math.floor(slicedn19 + 0.5), math.floor(sliced24 + 0.5), math.floor(sliced26 + 0.5), math.floor(sliced25 + 0.5), sliced23 and "" or ", guard is faster, going at your max safe speed")
				end

				local function slicedfn55()
					local slicedn19 = math.max(0, safeCarry.Height)
					local sliced21 = tbl4.Root()
					local character2 = localPlayer.Character
					if slicedn19 <= 0.5 or not sliced21 or not character2 then
						return
					end
					local slicedn20 = sliced19.Y + slicedn19
					if slicedn20 - 2 <= sliced21.Position.Y then
						return
					end
					local rotation = sliced21.CFrame.Rotation
					local slicedn21 = CFrame.new(Vector3.new(sliced21.Position.X, slicedn20, sliced21.Position.Z)) * rotation

					pcall(function()
						character2:PivotTo(slicedn21)
						sliced21.AssemblyLinearVelocity = Vector3.zero
						sliced21.AssemblyAngularVelocity = Vector3.zero
					end)
				end

				slicedfn54()
				local sliced21 = safeCarry.NewHuman(true)
				local sliced22 = tbl4.Root()
				local slicedn19 = math.clamp((sliced22 and sliced22.Position.Z or sliced19.Z) + sliced21.Lane, -425, -300)
				local now2 = os.clock()

				if safeCarry.CarryReact > 0 and not (safeCarry.Teleport and not tbl4.AntiGuard.Enabled) then
					local slicedn20 = os.clock() + safeCarry.React(0, safeCarry.CarryReact)

					while os.clock() < slicedn20 and not slicedfn13(arg) do
						RunService.Heartbeat:Wait()
					end
				end

				local slicedn20 = 0

				if safeCarry.CarryStyle ~= "Walk" then
					slicedfn55()
				end

				while not slicedfn13(arg) do
					local sliced23 = tbl4.Root()
					if not sliced23 then
						return false
					end

					if not tbl4.Steal.Carrying then
						if now <= safeCarry.LastDelivered then
							return true
						end
						task.wait(safeCarry.Teleport and 0.03 or 0.1)
						if now <= safeCarry.LastDelivered then
							return true
						end

						if now <= safeCarry.LastFailed then
							str2 = "Delivery was rewound, too fast for your speed"
							return false
						end

						if not safeCarry.PlanOk and tbl4.Steal.CarryUid then
							safeCarry.Blocked[tbl4.Steal.CarryUid] = true
							str2 = string.format("The guard caught you with %s, it is faster than your max safe speed, skipping this egg", tostring(safeCarry.Category))
							return false
						end

						slicedn20 += 1
						if safeCarry.RecoverTries < slicedn20 then
							str2 = "The egg is gone"
							return false
						end
						str2 = "Egg dropped, taking it back"
						if not (tbl4.SafeCarry.Teleport and not tbl4.AntiGuard.Enabled and tbl4.SafeCarry.Regrab(arg, tbl4.Steal.CarryUid)) and not slicedfn50(arg) then
							str2 = "Could not take the egg back"
							return false
						end
						local slicedn21 = 0

						while slicedfn31() and slicedn21 < 4 and not slicedfn13(arg) do
							slicedn21 += RunService.Heartbeat:Wait()
						end

						local slicedn22 = math.min(now, os.clock())
						slicedfn54()

						if safeCarry.CarryStyle ~= "Walk" then
							slicedfn55()
						end

						sliced23 = tbl4.Root()
						if not sliced23 then
							return false
						end
						now = slicedn22
					end

					local now3 = os.clock()
					local slicedn21 = math.max(now3 - now2, 0.0041666666666666666)
					local flag3 = safeCarry.CarryStyle == "Walk"
					local slicedn22 = flag3 and 0 or math.max(0, safeCarry.Height)
					local sliced24, sliced25 = sliced21.Step(slicedn21, slicedn22 <= 0.5 and humanoid or nil, humanoid and humanoid.FloorMaterial ~= Enum.Material.Air)
					if safeCarry.Teleport and not tbl4.AntiGuard.Enabled then
						-- Instant TP without Anti Guard: straight line at full carry speed, no human slow-downs or zigzag
						sliced24, sliced25 = 1, 0
					end
					local slicedn23 = math.clamp(slicedn19 + sliced25, -425, -300)
					local vector = sliced23.Position.X > slicedn17 + 2 and Vector3.new(slicedn17, sliced23.Position.Y, slicedn23) or sliced19
					local sliced26, sliced27 = safeCarry.Avoid(sliced23.Position, vector)

					if not sliced27 then
						sliced26 = vector
					end

					local vector2 = Vector3.new(sliced26.X - sliced23.Position.X, 0, sliced26.Z - sliced23.Position.Z)
					if vector2.Magnitude < 2 and sliced26 == sliced19 then
						break
					end
					local slicedn24 = math.max(slicedn18 * sliced24, safeCarry.FloorSpeed or 0)

					if os.clock() < (safeCarry.SlowUntil or 0) then
						slicedn24 *= safeCarry.SlowFactor
					end

					if flag3 then
						pcall(function()
							if humanoid and vector2.Magnitude > 0.01 then
								humanoid:MoveTo(sliced23.Position + vector2.Unit * math.min(vector2.Magnitude, 30))
							end
						end)
					elseif slicedn22 > 0.5 then
						local slicedn25 = math.clamp(safeCarry.ClimbShare, 0.1, 0.9)
						local y = sliced19.Y
						local slicedn26 = math.max(0, sliced23.Position.X - slicedn17)
						local slicedn27 = slicedn22 * math.sqrt(1 - slicedn25 * slicedn25) / slicedn25
						local slicedn28 = y + slicedn22

						if sliced26 == sliced19 or slicedn26 <= slicedn27 then
							slicedn28 = y + slicedn22 * math.clamp((sliced26 == sliced19 and 0 or slicedn26) / math.max(slicedn27, 1), 0, 1)
						end

						local slicedn29 = math.clamp((slicedn28 - sliced23.Position.Y) / 0.12, -slicedn24 * slicedn25, slicedn24 * slicedn25)
						local sliced28 = math.sqrt(math.max(slicedn24 * slicedn24 - slicedn29 * slicedn29, 0))
						local vector3 = vector2.Magnitude > 0.01 and vector2.Unit * math.min(sliced28, vector2.Magnitude / 0.05) or Vector3.zero

						pcall(function()
							sliced23.AssemblyLinearVelocity = Vector3.new(vector3.X, slicedn29, vector3.Z)
						end)
					else
						local vector3 = vector2.Magnitude > 0.01 and vector2.Unit * math.min(slicedn24, vector2.Magnitude / 0.05) or Vector3.zero

						pcall(function()
							sliced23.AssemblyLinearVelocity = Vector3.new(vector3.X, sliced23.AssemblyLinearVelocity.Y, vector3.Z)

							if safeCarry.RunAnimate and humanoid and vector2.Magnitude > 0.01 then
								humanoid:Move(vector2.Unit, false)
							end
						end)
					end

					RunService.Heartbeat:Wait()
					now2 = now3
				end

				if humanoid then
					pcall(function()
						local sliced23 = tbl4.Root()

						if safeCarry.CarryStyle == "Walk" and sliced23 then
							humanoid:MoveTo(sliced23.Position)
						end

						humanoid:Move(Vector3.zero, false)
					end)
				end

				local slicedn21 = 0

				while slicedn21 < 2 and not slicedfn13(arg) do
					if safeCarry.LastDelivered >= now then
						return true
					end

					if now <= safeCarry.LastFailed then
						str2 = "Delivery was rewound, too fast for your speed"
						return false
					end

					if not tbl4.Steal.Carrying then
						break
					end
					slicedn21 += RunService.Heartbeat:Wait()
				end

				if tbl4.Steal.Carrying then
					task.wait(0.2)
					local eggState = tbl.EggState

					if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
						pcall(eggState.DropFieldEgg, "PlayerRequest")
					end
				end

				return safeCarry.LastDelivered >= now
			end

			-- Instant TP (the standalone's method, from the first hop to the safe zone). Used whenever Anti Guard is off;
			-- with Anti Guard on, the hub's own line-drop route below still runs.
			local InstantEngine = (function()
				local conns, alive = {}, true
				local EggState = tbl.EggState
				local function remote(name)
					return networking:FindFirstChild(name)
				end
				local function root()
					return tbl4.Root()
				end
				local function walkSpeed()
					return tbl4.WalkSpeed()
				end

local CFG = {
	SpeedCap = 1.15, -- never above 115% of the walk speed
	HopRatio = 1.515, -- hop distance = walk speed * ratio (a distance, not a speed)
	HopMin = 40,
	HopGap = 0.06, -- seconds between two hops (learned: grows after a pull-back, shrinks after a clean hop)
	HopGapMin = 0.06,
	HopGapMax = 0.2,
	HopRetries = 6,
	HopLift = 42, -- height of the hops above the start
	LandOffset = 14, -- landing spot in front of the line
	LandSettle = 0.08,
	DropDelay = 0.05,
	GrabInterval = 0.03,
	RegrabFar = 40, -- egg further than this: teleport onto it, otherwise run to it
	Height = 70, -- the safe-zone run starts above the base and comes down (same as the hub)
	ClimbShare = 0.5,
	CarryRatio = 0.9,
	EasyRatio = 1.3,
}
local FPS = { 60, 30, 0.15 }

local state = { Carrying = false, Uid = nil, Delivered = 0, Busy = false, Cancel = false, Mult = 1, PulledAt = 0, HeldSeen = 0, GuessedDrop = false }

if type(EggState) == "table" and type(EggState.CarryChanged) == "table" and type(EggState.CarryChanged.Connect) == "function" then
	conns[#conns + 1] = EggState.CarryChanged:Connect(function(arg)
		local carrying = type(arg) == "table" and arg.IsCarrying == true
		if carrying and arg.GuardDisabled == true then
			carrying = false
		end
		state.GuessedDrop = false
		if carrying then
			state.HeldSeen = os.clock()
		end
		if carrying and type(arg.Uid) == "string" then
			state.Uid = arg.Uid
			local mult = tonumber(arg.SpeedMultiplier)
			if mult and mult > 0 then
				state.Mult = mult
			end
		end
		state.Carrying = carrying
	end)
end

pcall(function()
	conns[#conns + 1] = remote("RE/EggWorld/FieldEggRedeemVerdict").OnClientEvent:Connect(function()
		state.Delivered = os.clock()
	end)
end)

-- the server pulling us back ("Relocate") is noted so the hop is simply repeated
pcall(function()
	conns[#conns + 1] = remote("RE/RigSync/Refresh").OnClientEvent:Connect(function(arg)
		if type(arg) == "table" and arg.Action == "Relocate" then
			state.PulledAt = os.clock()
		end
	end)
end)

local function takeEgg(uid)
	if type(uid) == "string" and type(EggState) == "table" and type(EggState.CarryFieldEgg) == "function" then
		pcall(EggState.CarryFieldEgg, uid)
	end
end

local function dropEgg()
	if type(EggState) == "table" and type(EggState.DropFieldEgg) == "function" then
		pcall(EggState.DropFieldEgg, "PlayerRequest")
	end
end

-- the prompt of the egg itself (nearest egg prompt to the egg's position), never one of another egg
local function promptNear(position, radius)
	local best, bestDistance = nil, radius
	for _, child in ipairs(workspace:GetChildren()) do
		if child.Name == "SmartPromptPart" and child:IsA("BasePart") then
			local prompt = child:FindFirstChild("CarryAreaEgg")
			if prompt and prompt:IsA("ProximityPrompt") then
				local distance = (child.Position - position).Magnitude
				if distance < bestDistance then
					best, bestDistance = prompt, distance
				end
			end
		end
	end
	return best
end

-- the carried egg is welded to the character: used to catch a missed carry signal (same check as the hub)
local function heldByMe(uid)
	local character = localPlayer.Character
	if type(uid) ~= "string" or not character then
		return false
	end
	local egg = workspace:FindFirstChild(uid)
	if not egg then
		return false
	end
	for _, d in ipairs(egg:GetDescendants()) do
		if d:IsA("WeldConstraint") or d:IsA("JointInstance") then
			local ok, a, b = pcall(function()
				return d.Part0, d.Part1
			end)
			if ok and ((a and a:IsDescendantOf(character)) or (b and b:IsDescendantOf(character))) then
				return true
			end
		end
	end
	return false
end

task.spawn(function()
	while alive do
		task.wait(0.2)
		if not state.Carrying then
			if state.GuessedDrop and heldByMe(state.Uid) then
				state.GuessedDrop, state.Carrying, state.HeldSeen = false, true, os.clock()
			end
		elseif heldByMe(state.Uid) then
			state.HeldSeen = os.clock()
		elseif os.clock() - state.HeldSeen > 0.8 then
			state.Carrying, state.GuessedDrop = false, true
		end
	end
end)

local function snapshot()
	local list = {}
	local ok, result = pcall(function()
		return remote("RF/EggWorld/AskFieldEggSnapshot"):InvokeServer()
	end)
	local records = ok and type(result) == "table" and result.Records or nil
	if type(records) ~= "table" then
		return list
	end
	for _, record in pairs(records) do
		if type(record) == "table" and type(record.Uid) == "string" and (record.State == "Slot" or record.State == "Dropped") and typeof(record.BottomCFrame) == "CFrame" then
			list[#list + 1] = record
		end
	end
	return list
end

local function eggPosition(uid)
	for _, record in ipairs(snapshot()) do
		if record.Uid == uid then
			return record.BottomCFrame.Position
		end
	end
	return nil
end

local function status(text)
	str2 = text
end

local function frozenCamera()
	local camera = workspace.CurrentCamera
	if not camera then
		return function() end
	end
	local oldType = camera.CameraType
	local frame = camera.CFrame
	pcall(function()
		camera.CameraType = Enum.CameraType.Scriptable
		camera.CFrame = frame
	end)
	return function()
		pcall(function()
			camera.CameraType = oldType
		end)
	end
end

local fpsGen = 0
local function fpsOn()
	if typeof(setfpscap) ~= "function" or tbl4.SafeCarry.TpFpsCap == false then
		return
	end
	fpsGen += 1
	local mine = fpsGen
	task.spawn(function()
		local high = true
		local started = os.clock()
		while fpsGen == mine and os.clock() - started < 60 do
			pcall(setfpscap, high and FPS[1] or FPS[2])
			high = not high
			task.wait(FPS[3])
		end
	end)
end

local function fpsOff()
	fpsGen += 1
	if typeof(setfpscap) == "function" then
		pcall(setfpscap, 240)
	end
end

-- a still copy of the player stays where the egg was taken during the flight; removed on arrival
local stealClone = nil
local function dropClone()
	local copy = stealClone
	stealClone = nil
	if copy then
		pcall(function()
			copy:Destroy()
		end)
	end
end

local function postClone()
	dropClone()
	local character = localPlayer.Character
	if not character then
		return
	end
	local was = character.Archivable
	character.Archivable = true
	local copy = character:Clone()
	character.Archivable = was
	if copy then
		for _, d in ipairs(copy:GetDescendants()) do
			if d:IsA("LuaSourceContainer") or d:IsA("Humanoid") then
				pcall(function()
					d:Destroy()
				end)
			elseif d:IsA("BasePart") then
				d.Anchored = true
				d.CanCollide = false
				d.CanTouch = false
				d.CanQuery = false
			end
		end
		copy.Name = "Clone"
		copy.Parent = workspace
		stealClone = copy
	end
end

local function lineInfo()
	local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
	world = world and world:FindFirstChild("Areas")
	world = world and world:FindFirstChild("SeparationLine")
	local ok = world and world:IsA("BasePart")
	return ok and world.Position.X or 552.2, ok and world.Position.Y or 67.67
end

local function homePoint()
	for _, def in ipairs({
		{ { "GearGiver_Slap", "Podium" }, Vector3.new(-16.415, 21.072, -6.106) },
		{ { "World", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" }, Vector3.new(-26.776, 1.75, 18.665) },
		{ { "__OBJECTS", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" }, Vector3.new(-26.776, 1.75, 18.665) },
	}) do
		local node = workspace
		for _, name in ipairs(def[1]) do
			node = node and node:FindFirstChild(name) or nil
		end
		if node and node:IsA("BasePart") then
			return node.CFrame:PointToWorldSpace(def[2])
		end
	end
	return Vector3.new(528.7, 70.57, -364.11)
end

local function place(position)
	local r = root()
	if not r then
		return
	end
	pcall(function()
		r.CFrame = CFrame.new(position) * CFrame.Angles(0, math.rad(90), 0)
		r.AssemblyLinearVelocity = Vector3.zero
		r.AssemblyAngularVelocity = Vector3.zero
	end)
end

-- portals / arenas / teleporters are walked around (same list as the hub)
local dangerCache, dangerAt = {}, 0
local function dangers()
	if os.clock() - dangerAt < 1 then
		return dangerCache
	end
	dangerAt = os.clock()
	local list = {}
	local function add(inst)
		local ok, cf, size = pcall(function()
			if inst:IsA("Model") then
				return inst:GetBoundingBox()
			elseif inst:IsA("BasePart") then
				return inst.CFrame, inst.Size
			end
		end)
		if ok and cf and size then
			local half = Vector3.new(math.abs(size.X), 0, math.abs(size.Z)) * 0.5
			local rot = (cf - cf.Position):VectorToWorldSpace(half)
			local rx = math.max(math.abs(rot.X), half.X, half.Z)
			local rz = math.max(math.abs(rot.Z), half.X, half.Z)
			list[#list + 1] = { MinX = cf.Position.X - rx, MaxX = cf.Position.X + rx, MinZ = cf.Position.Z - rz, MaxZ = cf.Position.Z + rz }
		end
	end
	local function bad(name)
		if name == "ScrambleLocalVisuals" or name == "DrScrambleEvent" then
			return false
		end
		name = string.lower(name)
		return string.find(name, "portal", 1, true) or string.find(name, "teleport", 1, true) or string.find(name, "mech", 1, true) or string.find(name, "arena", 1, true) or string.find(name, "scramble", 1, true)
	end
	for _, child in ipairs(workspace:GetChildren()) do
		if (child:IsA("Model") or child:IsA("BasePart") or child:IsA("Folder")) and bad(child.Name) then
			if child:IsA("Folder") then
				for _, inner in ipairs(child:GetChildren()) do
					add(inner)
				end
			else
				add(child)
			end
		end
	end
	local build = workspace:FindFirstChild("World")
	build = build and build:FindFirstChild("Build")
	if build then
		for _, child in ipairs(build:GetChildren()) do
			if bad(child.Name) then
				for _, inner in ipairs(child:GetChildren()) do
					add(inner)
				end
			end
		end
	end
	dangerCache = list
	return list
end

-- if the straight line crosses a danger zone, aim at the corner of it instead
local function avoid(from, to)
	for _, d in ipairs(dangers()) do
		local x0, x1, z0, z1 = d.MinX - 12, d.MaxX + 12, d.MinZ - 12, d.MaxZ + 12
		local inside = from.X >= x0 and from.X <= x1 and from.Z >= z0 and from.Z <= z1
		if not inside then
			local t0, t1, hit = 0, 1, true
			for _, axis in ipairs({ { from.X, to.X - from.X, x0, x1 }, { from.Z, to.Z - from.Z, z0, z1 } }) do
				local pos, delta, lo, hi = axis[1], axis[2], axis[3], axis[4]
				if math.abs(delta) < 1e-6 then
					if pos < lo or pos > hi then
						hit = false
					end
				else
					local ta, tb = (lo - pos) / delta, (hi - pos) / delta
					if ta > tb then
						ta, tb = tb, ta
					end
					t0, t1 = math.max(t0, ta), math.min(t1, tb)
					if t0 > t1 then
						hit = false
					end
				end
			end
			if hit then
				local zLow, zHigh = z0 - 2, z1 + 2
				local z = math.abs(from.Z - zLow) <= math.abs(from.Z - zHigh) and zLow or zHigh
				if z < -440 or z > -290 then
					z = z == zLow and zHigh or zLow
				end
				local x = math.abs(from.X - x0) <= math.abs(from.X - x1) and x0 or x1
				if math.abs(from.Z - z) < 3 then
					x = math.abs(to.X - x0) <= math.abs(to.X - x1) and x0 or x1
				end
				return Vector3.new(x, to.Y, z)
			end
		end
	end
	return to
end

-- the hub's "Run" way to the egg: straight on the ground at 115% of the walk speed (never faster).
-- From the base side it first walks out to the safe-zone point, like the hub does.
local function runToEgg(uid, egg)
	local lineX = lineInfo()
	local home = homePoint()
	local character = localPlayer.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		humanoid.PlatformStand = false
		if character:FindFirstChildWhichIsA("Tool") then
			pcall(function()
				humanoid:UnequipTools()
			end)
		end
	end

	local r = root()
	if not r then
		return false
	end
	local stage = "field"
	if r.Position.X < lineX - 2 and Vector3.new(r.Position.X - home.X, 0, r.Position.Z - home.Z).Magnitude > 20 then
		stage = "safe"
	end

	local started, lastCheck, lastPos, lastTake = os.clock(), os.clock(), r.Position, 0
	while os.clock() - started < 120 and not state.Cancel do
		r = root()
		if not r then
			return false
		end
		local flatEgg = Vector3.new(egg.X - r.Position.X, 0, egg.Z - r.Position.Z)
		if stage == "field" and flatEgg.Magnitude <= 2.5 then
			break
		end
		local target = egg
		if stage == "safe" then
			if Vector3.new(home.X - r.Position.X, 0, home.Z - r.Position.Z).Magnitude <= 6 then
				stage = "field"
			else
				target = home
			end
		end

		local waypoint = avoid(r.Position, target)
		local flat = Vector3.new(waypoint.X - r.Position.X, 0, waypoint.Z - r.Position.Z)
		local unit = flat.Magnitude > 0.01 and flat.Unit or Vector3.zero
		local speed = math.max(walkSpeed() * CFG.SpeedCap, 8)
		local v = unit * math.min(speed, flat.Magnitude / 0.05)
		pcall(function()
			r.AssemblyLinearVelocity = Vector3.new(v.X, r.AssemblyLinearVelocity.Y, v.Z)
			if humanoid and unit.Magnitude > 0 then
				humanoid:Move(unit, false)
			end
		end)

		-- stuck on something: jump
		if os.clock() - lastCheck >= 1.5 then
			if (r.Position - lastPos).Magnitude < 3 and humanoid and flatEgg.Magnitude > 15 then
				pcall(function()
					humanoid.Jump = true
				end)
			end
			lastPos, lastCheck = r.Position, os.clock()
		end

		-- close enough for the prompt: ask for the egg while arriving
		if stage == "field" and flatEgg.Magnitude <= 9 and os.clock() - lastTake > 0.1 then
			lastTake = os.clock()
			takeEgg(uid)
		end
		RunService.Heartbeat:Wait()
	end

	r = root()
	if r then
		pcall(function()
			r.AssemblyLinearVelocity = Vector3.new(0, r.AssemblyLinearVelocity.Y, 0)
			if humanoid then
				humanoid:Move(Vector3.zero, false)
			end
		end)
	end
	return state.Carrying or (r ~= nil and Vector3.new(egg.X - r.Position.X, 0, egg.Z - r.Position.Z).Magnitude <= 6)
end

-- current position of an egg lying in the world (cheap), with the snapshot as fallback
local function eggNow(uid, cache)
	local node = workspace:FindFirstChild(uid)
	local slots = workspace:FindFirstChild("AreaEggSlotsClient")
	node = node or (slots and slots:FindFirstChild(uid))
	if node then
		local ok, pos = pcall(function()
			return node:GetPivot().Position
		end)
		if ok and pos then
			cache.Pos, cache.At = pos, os.clock()
			return pos
		end
	end
	if os.clock() - cache.At >= 0.5 then
		cache.At = os.clock()
		cache.Pos = eggPosition(uid) or cache.Pos
	end
	return cache.Pos
end

-- take the egg that lies next to us (also used to take it back after the drop): follow it, fire its prompt and send the request
local function grab(uid, timeout)
	local cache = { At = 0 }
	local waited, since = 0, 1
	while not state.Carrying and waited < timeout and not state.Cancel do
		local r = root()
		local egg = eggNow(uid, cache)
		local dt = math.max(RunService.Heartbeat:Wait(), 1 / 240)
		waited += dt
		since += dt
		if r and egg then
			local delta = egg - r.Position
			if delta.Magnitude > 2 then
				local pace = math.max(walkSpeed() * CFG.SpeedCap, 16)
				local v = delta / math.max(0.08, dt)
				if v.Magnitude > pace then
					v = v.Unit * pace
				end
				pcall(function()
					r.AssemblyLinearVelocity = v + Vector3.new(0, workspace.Gravity * dt * 0.5, 0)
					r.AssemblyAngularVelocity = Vector3.zero
				end)
			end
			if since >= CFG.GrabInterval then
				since = 0
				local prompt = promptNear(egg - Vector3.new(0, 3, 0), 10)
				if prompt and typeof(fireproximityprompt) == "function" then
					pcall(function()
						prompt.HoldDuration = 0
					end)
					pcall(fireproximityprompt, prompt)
				end
				task.spawn(takeEgg, uid)
			end
		elseif since >= CFG.GrabInterval then
			since = 0
			task.spawn(takeEgg, uid)
		end
	end
	local r = root()
	if r then
		pcall(function()
			r.AssemblyLinearVelocity = Vector3.zero
		end)
	end
	return state.Carrying and state.Uid == uid
end

local function regrab(uid)
	if state.Carrying then
		return true
	end
	local r = root()
	local egg = eggPosition(uid)
	if r and egg and Vector3.new(r.Position.X - egg.X, 0, r.Position.Z - egg.Z).Magnitude > CFG.RegrabFar then
		status("The egg fell far behind, teleporting onto it")
		place(egg + Vector3.new(0, 3, 0))
	else
		status("The egg fell close, taking it back")
	end
	return grab(uid, 3)
end

local function groundY(position, fallback)
	local y = fallback
	pcall(function()
		local params = RaycastParams.new()
		params.FilterType = Enum.RaycastFilterType.Exclude
		params.FilterDescendantsInstances = { localPlayer.Character }
		params.IgnoreWater = true
		local hit = workspace:Raycast(position + Vector3.new(0, 60, 0), Vector3.new(0, -140, 0), params)
		if hit and hit.Material ~= Enum.Material.Water and math.abs(hit.Position.Y - fallback) < 40 then
			y = hit.Position.Y + 3.5
		end
	end)
	return y
end

-- safe zone: same route as the Normal mode: checkpoint 7 studs past the line, then the base.
-- Speed = the hub's carry plan (never above 115% of the walk speed), the run starts above the base and comes down.
local function carrySpeed(distance)
	local ws = walkSpeed()
	local base = ws * math.min(CFG.CarryRatio, CFG.SpeedCap) * state.Mult
	local fast = base * 1.5 -- SpeedRatio
	local excess = 5.5 * base -- ExcessSeconds
	local limit = fast
	if distance and distance > excess then
		limit = math.min(fast, base * distance / (distance - excess))
	end
	return math.min(math.max(math.min(base * CFG.EasyRatio, limit), base), math.max(ws * CFG.SpeedCap, base))
end

local function runHome(lineX, laneZ)
	local started = os.clock()
	local home = homePoint()
	local checkpoint = lineX - 7
	local height = CFG.Height
	local share = math.clamp(CFG.ClimbShare, 0.1, 0.9)
	local descent = height * math.sqrt(1 - share * share) / share
	local character = localPlayer.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		humanoid.PlatformStand = false
	end

	-- rise above the base first (no horizontal move), like the hub
	local r = root()
	if r and character and height > 0.5 and home.Y + height - 2 > r.Position.Y then
		pcall(function()
			character:PivotTo(CFrame.new(Vector3.new(r.Position.X, home.Y + height, r.Position.Z)) * r.CFrame.Rotation)
			r.AssemblyLinearVelocity = Vector3.zero
			r.AssemblyAngularVelocity = Vector3.zero
		end)
	end

	-- the speed is planned once, at the start, from the distance still to go (the hub does the same)
	local start = root()
	local speed = carrySpeed(start and (Vector3.new(start.Position.X - home.X, 0, start.Position.Z - home.Z).Magnitude + math.max(0, height) * 2) or nil)

	local last = os.clock()
	local timeout = 0
	status("Safe zone")
	while state.Carrying and state.Delivered < started and not state.Cancel and timeout < 25 do
		r = root()
		if not r then
			return false
		end
		local now = os.clock()
		local dt = math.max(now - last, 1 / 240)
		last = now
		timeout += dt

		local toHome = r.Position.X <= checkpoint + 2
		local target = toHome and home or Vector3.new(checkpoint, home.Y, laneZ)
		if toHome and Vector3.new(home.X - r.Position.X, 0, home.Z - r.Position.Z).Magnitude < 2 then
			break
		end
		local aim = avoid(r.Position, target)
		local flat = Vector3.new(aim.X - r.Position.X, 0, aim.Z - r.Position.Z)
		local remaining = toHome and 0 or math.max(0, r.Position.X - checkpoint)
		local wantY = home.Y + height
		if toHome or remaining <= descent then
			wantY = home.Y + height * math.clamp(remaining / math.max(descent, 1), 0, 1)
		end
		local vy = math.clamp((wantY - r.Position.Y) / 0.12, -speed * share, speed * share)
		local horizontal = math.sqrt(math.max(speed * speed - vy * vy, 0))
		local v = flat.Magnitude > 0.01 and flat.Unit * math.min(horizontal, flat.Magnitude / 0.05) or Vector3.zero
		pcall(function()
			r.AssemblyLinearVelocity = Vector3.new(v.X, vy, v.Z)
		end)
		RunService.Heartbeat:Wait()
	end

	if humanoid then
		pcall(function()
			humanoid:Move(Vector3.zero, false)
		end)
	end

	local settle = 0
	while settle < 2 and state.Delivered < started and state.Carrying and not state.Cancel do
		settle += RunService.Heartbeat:Wait()
	end
	-- still in the hands at home: put it down so the base takes it
	if state.Carrying and state.Delivered < started and not state.Cancel then
		task.wait(0.2)
		dropEgg()
		local waited = 0
		while state.Delivered < started and waited < 1 do
			waited += RunService.Heartbeat:Wait()
		end
	end
	return state.Delivered >= started
end

local function instantTP(uid)
	local started = os.clock()
	local lineX, lineY = lineInfo()
	local r = root()
	if not r then
		return false
	end
	local laneZ = math.clamp(r.Position.Z, -425, -300)
	local landing = Vector3.new(lineX + CFG.LandOffset, lineY + 3.35, laneZ)

	-- hops towards the line; a pull-back repeats the same hop with a longer pause (the pause is learned)
	local hopStep = math.max(walkSpeed() * CFG.HopRatio, CFG.HopMin)
	local hopY = r.Position.Y + CFG.HopLift
	local x = r.Position.X
	local retries = 0
	local releaseCamera = frozenCamera()
	state.ReleaseCamera = releaseCamera
	pcall(postClone)
	fpsOn()

	while x - hopStep > landing.X and not state.Cancel do
		if not state.Carrying then
			-- the server let go of the egg on the way: take it back right away
			if not regrab(uid) then
				break
			end
			local current = root()
			if current then
				x = math.min(x, current.Position.X)
			end
			continue
		end

		local nextX = x - hopStep
		status(string.format("Instant TP: hopping home, X %d", math.floor(nextX)))
		local pulledBefore = state.PulledAt
		local held = 0
		while held < CFG.HopGap do
			place(Vector3.new(nextX, hopY, laneZ))
			held += RunService.Heartbeat:Wait()
		end

		local check = root()
		local pulled = state.PulledAt > pulledBefore or (check ~= nil and (check.Position.X - nextX > 10 or check.AssemblyLinearVelocity.Magnitude > 150))
		if pulled and state.Carrying and not state.Cancel then
			retries += 1
			CFG.HopGap = math.min(CFG.HopGapMax, CFG.HopGap + 0.02)
			if retries > CFG.HopRetries then
				break
			end
			status(string.format("Instant TP: pulled back, retry %d/%d", retries, CFG.HopRetries))
			local settle = 0
			while settle < 0.12 and not state.Cancel do
				place(Vector3.new(x, hopY, laneZ))
				settle += RunService.Heartbeat:Wait()
			end
		else
			x = nextX
			CFG.HopGap = math.max(CFG.HopGapMin, CFG.HopGap - 0.01)
		end
	end

	-- landing in front of the line
	status("Instant TP: landing next to the line")
	landing = Vector3.new(landing.X, groundY(landing, landing.Y), landing.Z)
	local function land()
		local current = root()
		-- never jump backwards: if we are already closer to the line than the landing spot, stay
		if current and current.Position.X <= landing.X + 1 and current.Position.Y > landing.Y - 25 then
			pcall(function()
				current.AssemblyLinearVelocity = Vector3.zero
			end)
			return
		end
		place(landing)
	end
	land()
	for attempt = 1, 3 do
		local settle = 0
		while settle < CFG.LandSettle and not state.Cancel do
			settle += RunService.Heartbeat:Wait()
		end
		local landed = root()
		if state.Carrying and landed and (landed.Position.X - landing.X > 12 or landed.Position.Y < landing.Y - 25) then
			status("Instant TP: landing retry " .. attempt)
			land()
		else
			break
		end
	end
	dropClone()

	-- drop at the line, take it back
	if state.Carrying and not state.Cancel then
		local delay = 0
		while delay < CFG.DropDelay do
			delay += RunService.Heartbeat:Wait()
		end
		status("Instant TP: dropping the egg")
		dropEgg()
		local waited = 0
		while state.Carrying and waited < 1 and not state.Cancel do
			waited += RunService.Heartbeat:Wait()
		end
		local current = root()
		if current then
			pcall(function()
				current.AssemblyLinearVelocity = Vector3.zero
				current.AssemblyAngularVelocity = Vector3.zero
			end)
		end
		-- egg is down: let go of the camera and the copy, then take it back
		releaseCamera()
		dropClone()
		status("Instant TP: taking the egg back")
		if not grab(uid, 3) and not regrab(uid) then
			fpsOff()
			status("Could not take the egg back")
			return false
		end
		dropClone()
	end
	releaseCamera()

	-- straight to the safe zone
	local ok = false
	if state.Carrying then
		ok = runHome(lineX, laneZ)
	end
	fpsOff()
	return ok or state.Delivered >= started
end


				local E = {}

				function E.deliver(uid, cancelFn)
					state.Cancel = false
					state.Uid = uid
					if tbl4.Steal.Carrying == true and not state.Carrying then
						state.Carrying, state.HeldSeen, state.GuessedDrop = true, os.clock(), false
					end
					local running = true
					task.spawn(function()
						while running do
							if cancelFn and cancelFn() then
								state.Cancel = true
							end
							task.wait(0.05)
						end
					end)
					local ok, result = pcall(instantTP, uid)
					running = false
					pcall(dropClone)
					if state.ReleaseCamera then
						pcall(state.ReleaseCamera)
						state.ReleaseCamera = nil
					end
					pcall(fpsOff)
					if not ok then
						status("Instant TP error: " .. tostring(result))
						return false
					end
					return result == true
				end

				slicedfn4(function()
					alive = false
					for _, c in ipairs(conns) do
						pcall(function()
							c:Disconnect()
						end)
					end
				end)
				return E
			end)()

			tbl4.InstantEngine = InstantEngine
			tbl4.SafeCarry.InstantHome = function(arg)
				local uid = tbl4.Steal.CarryUid
				if not tbl4.AntiGuard.Enabled and type(uid) == "string" then
					return InstantEngine.deliver(uid, function()
						return slicedfn13(arg)
					end)
				end
				return tbl4.SafeCarry.LineDropHome(arg)
			end

			local function deliverOnce(arg)
				local antiGuard = tbl4.AntiGuard

				if antiGuard.Enabled and not (tbl4.SafeCarry.StopMode or tbl4.SafeCarry.Teleport) then
					local slicedn17 = 0

					while not antiGuard.Busy and slicedn17 < 1 and not slicedfn13(arg) do
						str2 = "Waiting for Anti Guard to start"
						slicedn17 += RunService.Heartbeat:Wait()
					end

					local busy = antiGuard.Busy
					local slicedn18 = 0

					while antiGuard.Busy and slicedn18 < 30 and not slicedfn13(arg) do
						str2 = "Anti Guard is slipping past the guard"
						slicedn18 += RunService.Heartbeat:Wait()
					end

					if busy then
						local slicedn19 = 0
						local slicedn20 = 0

						while slicedn19 < 10 and not slicedfn13(arg) do
							local sliced19 = slicedfn31()
							local ok, result = pcall(tbl4.Steal.HeldByMe)
							ok = ok and result == true
							local flag3 = not sliced19
							if flag3 and not ok then
								break
							end

							if flag3 and ok and not antiGuard.Busy then
								slicedn20 += RunService.Heartbeat:Wait()
								if not (slicedn20 >= (tbl4.SafeCarry.Teleport and 0.1 or 0.3)) then
									continue
								end
								break
							end

							str2 = sliced19 and "The guard hit you, waiting until you can move" or "Waiting for Anti Guard to finish"
							slicedn19 += RunService.Heartbeat:Wait()
							slicedn20 = 0
						end

						local ok, result = pcall(tbl4.Steal.HeldByMe)

						if ok and not result then
							tbl4.Steal.Carrying = false
						end

						local safeCarry = tbl4.SafeCarry
						local sliced19 = stealHome()
						local slicedn21 = not (safeCarry.Teleport or safeCarry.StopMode) and sliced19 and safeCarry.Enabled and safeCarry.CarryStyle ~= "Walk" and safeCarry.Height > 0.5 and sliced19.Y + safeCarry.Height or nil
						local slicedn22 = (safeCarry.Teleport or safeCarry.StopMode) and 0.7 or 0

						while slicedn22 < 0.8 and tbl4.Steal.Carrying and not slicedfn13(arg) do
							str2 = slicedn22 < 0.6 and "Anti Guard done, rising up" or "Anti Guard done, getting ready"
							local sliced20 = tbl4.Root()

							if sliced20 and slicedn21 then
								local slicedn23 = slicedn21 - sliced20.Position.Y
								local slicedn24 = slicedn22 < 0.6 and math.clamp(slicedn23 / math.max(0.6 - slicedn22, 0.1), -120, 120) or math.clamp(slicedn23 / 0.2, -30, 30)

								pcall(function()
									sliced20.AssemblyLinearVelocity = Vector3.new(0, slicedn24, 0)
								end)
							end

							slicedn22 += RunService.Heartbeat:Wait()
						end

						local ok2, result2 = pcall(tbl4.Steal.HeldByMe)

						if ok2 and not result2 then
							tbl4.Steal.Carrying = false
						else
							tbl4.SafeCarry.SlowUntil = os.clock() + 2
						end
					end
				end

				local slicedn17 = 0

				while not tbl4.Steal.Carrying and slicedn17 < slicedn10 and not slicedfn13(arg) do
					str2 = "Checking the egg in hand"
					slicedn17 += RunService.Heartbeat:Wait()
				end

				if not tbl4.Steal.Carrying then
					str2 = "The egg is gone, staying to look for it"
					local retaken = (tbl4.SafeCarry.Teleport and tbl4.SafeCarry.Regrab(arg, nil, true)) or slicedfn50(arg)

					if not retaken then
						str2 = "The egg is gone"
						return false
					end


					-- the egg was left on the ground (Anti Guard) and we walked back to it, so finish like the Normal mode does
					if tbl4.SafeCarry.Teleport then
						tbl4.ClearClones()
						str2 = "Egg retaken, carrying it home"
						return tbl4.SafeCarry.Home(arg)
					end
				end

				if tbl4.SafeCarry.Teleport then
					if tbl4.Steal.Carrying then
						tbl4.ClearClones()
					end
					return tbl4.SafeCarry.InstantHome(arg)
				end

				if tbl4.SafeCarry.LineDrop then
					return tbl4.SafeCarry.LineDropHome(arg)
				end

				if tbl4.SafeCarry.Enabled then
					return tbl4.SafeCarry.Home(arg)
				end
				local sliced19 = stealHome()
				local sliced20 = tbl4.Root()
				if not sliced19 or not sliced20 then
					return false
				end
				local slicedn18 = math.max(sliced20.Position.Y, sliced19.Y) + slicedn3

				local function slicedfn55()
					if tbl20.Uid and tbl20.Freed and tbl4.Steal.Carrying then
						return "priority"
					end
					return nil
				end

				local flag3 = true
				local slicedn19 = 0

				while true do
					local sliced21 = tbl4.Root()

					if not sliced21 then
						return false
					else
						str2 = "Flying home"
						local position = sliced21.Position
						local slicedn20 = math.max(slicedn18, position.Y)
						local sliced22, sliced23 = slicedfn33(Vector3.new(position.X + (sliced19.X - position.X) * 0.25, position.Y + (slicedn20 - position.Y) * 0.7, position.Z + (sliced19.Z - position.Z) * 0.25), arg, flag3, nil, nil, slicedfn55)

						if sliced22 then
							sliced22, sliced23 = slicedfn33(Vector3.new(sliced19.X, slicedn20, sliced19.Z), arg, flag3, nil, nil, slicedfn55)
						end

						if sliced22 then
							sliced22, sliced23 = slicedfn33(sliced19, arg, flag3, nil, nil, slicedfn55)
						end

						if sliced22 then
							local character = localPlayer.Character
							character = character and character:FindFirstChildOfClass("Humanoid")

							if character then
								character.PlatformStand = false
							end

							task.wait(0.2)
							if not tbl4.Steal.Carrying then
								str2 = "Arrived without the egg"
								return false
							end
							local eggState = tbl.EggState

							if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
								pcall(eggState.DropFieldEgg, "PlayerRequest")
							end

							return true
						end

						if sliced23 == "priority" then
							local uid2 = tbl20.Uid
							local freed = tbl20.Freed
							local sliced24 = tbl20
							tbl20.Uid = nil
							sliced24.Freed = nil
							local sliced25 = tbl4.Root()
							if not sliced25 or not uid2 or not freed then
								return false
							end

							if (freed - sliced25.Position).Magnitude <= slicedn4 * slicedn16 then
								str2 = "Best egg fell nearby, swapping eggs"
								local eggState = tbl.EggState

								if type(eggState) == "table" and type(eggState.DropFieldEgg) == "function" then
									pcall(eggState.DropFieldEgg, "PlayerRequest")
								end

								local slicedn21 = 0

								while tbl4.Steal.Carrying and slicedn21 < 1 do
									slicedn21 += RunService.Heartbeat:Wait()
								end

								if not slicedfn50(arg, uid2) then
									return false
								end
							else
								str2 = "Best egg fell far away, riding a guard hit to it"
								if not slicedfn53(arg, uid2, freed) then
									return false
								end
							end

							local sliced26 = tbl4.Root()
							slicedn19 = 0

							if sliced26 then
								slicedn18 = math.max(sliced26.Position.Y, sliced19.Y) + slicedn3
							end

							continue
						end

						if sliced23 == "dropped" and slicedn19 < huge then
							slicedn19 += 1
							if not slicedfn50(arg) then
								return false
							end
							continue
						end

						break
					end
				end

				return false
			end

			-- delivery with analyzer; learns from the server's answer (see Tune)
			local function slicedfn54(arg)
				local sc = tbl4.SafeCarry
				local A = tbl4.Analyzer
				local mode = tbl4.Method.Current()
				local island = A.Island()
				pcall(A.Begin, mode, { mode })
				tbl4.Tune.Apply()
				-- Instant TP without Anti Guard: nothing to wait for, so hop faster and trust the direct margin more
				if sc.Teleport and not tbl4.AntiGuard.Enabled then
					sc.HopGap = math.max(0.05, (tonumber(sc.HopGap) or 0.1) * 0.6)
					sc.DirectMargin = math.max(0.6, math.min(tonumber(sc.DirectMargin) or 1.2, 0.9))
				end
				A.Event("tune", string.format("hop %.2f every %.2fs, walk %.2f", tbl4.Tune.HopRatio, tbl4.Tune.HopGap, tbl4.Tune.Ratio))

				local attemptAt = os.clock()
				A.Event("attempt", mode)
				local okCall, callResult = pcall(deliverOnce, arg)
				pcall(tbl4.CarryCap.Off)

				if tbl4.CameraFrozen then
					local cam = workspace.CurrentCamera
					local savedType = tbl4.CameraFrozen
					tbl4.CameraFrozen = nil

					if cam then
						pcall(function()
							cam.CameraType = savedType
						end)
					end
				end
				local ok = okCall and callResult == true

				if not okCall then
					A.Event("error", tostring(callResult))
				end

				local rejected = sc.LastFailed >= attemptAt
				local relocated = A.RelocateAt >= attemptAt
				local cancelled = slicedfn13(arg)
				local reason

				if ok then
					reason = "delivered with " .. mode
				elseif rejected then
					reason = "server rejected the delivery"
					sc.DirectMargin = math.min((tonumber(sc.DirectMargin) or 1.2) + 0.3, 3)
					A.Event("margin", sc.DirectMargin)
				elseif relocated then
					reason = "server moved the player back"
				elseif cancelled then
					reason = "cancelled"
				else
					reason = "the egg was lost on the way"
				end

				if ok or rejected or relocated or not cancelled then
					A.Record(island, mode, ok)
					tbl4.Tune.Learn(mode, island, ok, rejected or relocated)
				end

				if ok then
					sc.DirectMargin = math.max((sc.Teleport and not tbl4.AntiGuard.Enabled) and 0.6 or 1.0, (tonumber(sc.DirectMargin) or 1.2) - 0.05)
				end

				pcall(A.Finish, ok, reason)
				return ok
			end

			local function slicedfn55(arg)
				local slicedn17 = tonumber(arg) or 0
				local tbl21 = { "", "K", "M", "B", "T", "Qa", "Qi" }
				local slicedn18 = 1

				while math.abs(slicedn17) >= 1000 and slicedn18 < #tbl21 do
					slicedn17 /= 1000
					slicedn18 += 1
				end

				return string.format(slicedn18 == 1 and "%.0f%s" or "%.2f%s", slicedn17, tbl21[slicedn18])
			end

			local function slicedfn56(arg)
				if not arg then
					return "None"
				end
				local format = string.format
				local str3 = tostring(arg.Category)
				local slicedn17 = tonumber(arg.Scale) or 0
				local tostring = tostring
				local areaId = arg.AreaId
				local sliced20 = format("%s  %.2fx  |  value %s  |  %s", str3, slicedn17, slicedfn55(arg.Value), tostring(areaId))
				local str4

				if arg.State == "Dropped" then
					str4 = sliced20 .. "  |  dropped"
				elseif arg.State == "Carried" then
					str4 = sliced20 .. "  |  carried by a player"
				else
					str4 = sliced20
				end

				return str4
			end

			local flag3 = false
			local slicedn17 = 0.5
			local slicedn18 = 0.6
			local slicedn19 = 0
			local slicedn20 = 0

			local function slicedfn57()
				local sliced19 = slicedn5
				tbl4.Steal.Active = true

				-- Instant TP: the 60 / 30 FPS battle from the very start of the steal, released when the steal is over
				if tbl4.SafeCarry.Teleport and tbl4.SafeCarry.TpFpsCap ~= false then
					pcall(tbl4.CarryCap.On, "pulse")
					task.spawn(function()
						while tbl4.Steal.Active do
							task.wait(0.25)
						end
						pcall(tbl4.CarryCap.Off)
					end)
				end
				tbl4.Steal.Carrying = tbl4.Steal.Carrying == true

				if not tbl4.Steal.Carrying then
					tbl4.Steal.CarryUid = nil
				end

				local sliced20 = slicedfn19(false, true)
				local sliced21 = nil
				local sliced22 = nil
				local lastSkip = nil

				for _, sliced23 in ipairs(sliced20) do
					if sliced23.State == "Carried" then
						sliced22 = sliced22 or sliced23
					else
						local sliced24 = tbl4.SafeCarry.Unsafe(sliced23)

						if sliced24 then
							lastSkip = lastSkip or sliced24
						else
							sliced21 = sliced23
							break
						end
					end
				end

				local tbl21 = { sliced21 }
				uid = sliced21 and sliced21.Uid or nil
				tbl4.Steal.Wanted = sliced21 ~= nil
				str = slicedfn56(sliced21)

				if sliced22 then
					str ..= "  |  watching " .. tostring(sliced22.Category)
				end

				if not sliced21 then
					tbl4.Steal.Active = false
					lastSkip = lastSkip or tbl4.SafeCarry.LastSkip
					tbl4.SafeCarry.LastSkip = nil
					str2 = sliced22 and "Best egg is carried, waiting for it" or lastSkip and "Skipped: " .. lastSkip or "No egg matches"
					return false
				end

				if not tbl4.ClaimMovement("steal") then
					tbl4.Steal.Active = false
					str2 = "Waiting for Auto Place"
					return false
				end

				if tbl4.Treadmill.Riding or tbl4.OnBelt() then
					tbl4.ExitBelt()
				end

				flag3 = true
				tbl4.HoldBelt()

				local function slicedfn58(arg)
					str2 = arg
					local sliced23 = slicedfn51(sliced21, sliced19)
					local flag4 = false
					local str3 = nil

					if sliced23 then
						if slicedfn29(sliced21.Uid, sliced19) then
							flag4 = slicedfn54(sliced19)
							str3 = nil
						else
							str3 = str2
						end
					end

					slicedfn25()
					tbl4.Steal.Active = false
					tbl4.Steal.LastFinishedAt = os.clock()
					str3 = flag4 and "Delivered" or str3
					local str4

					if str3 then
						str4 = str3
					else
						str4 = sliced23 and "Run ended" or "That egg would not come free"
					end

					str2 = str4
					return true
				end

				local sliced23 = tbl4.Root()
				local position = typeof(sliced21.CFrame) == "CFrame" and sliced21.CFrame.Position or nil

				if sliced23 and position then
					local flag4 = (position - sliced23.Position).Magnitude <= slicedn15
					local areaId = sliced21.AreaId
					local flag5 = localPlayer:GetAttribute("AreaId") == areaId
					if flag4 or flag5 then
						return (slicedfn58("Target is right here, taking it"))
					end
				end

				if tbl4.SafeCarry.Enabled and tbl4.SafeCarry.Approach == "Run" then
					local sliced24 = tbl4.SafeCarry.RunTo(sliced21, sliced19)
					local flag4, sliced25

					if sliced24 then
						if slicedfn29(sliced21.Uid, sliced19) then
							flag4 = slicedfn54(sliced19)
							sliced25 = nil
						else
							sliced25 = str2
							flag4 = false
						end
					else
						tbl18[sliced21.Uid] = os.clock() + slicedn6
						sliced25 = nil
						flag4 = false
					end

					slicedfn25()
					tbl4.Steal.Active = false
					tbl4.Steal.LastFinishedAt = os.clock()
					str2 = flag4 and "Delivered" or sliced25 or (sliced24 and "Run ended" or "That egg would not come free")
					return true
				end

				local sliced24 = slicedfn19(true)
				local str3 = "FirstAreaEgg_" .. tostring(localPlayer.UserId)
				local tbl22 = {}

				for _, sliced25 in ipairs(sliced24) do
					if slicedfn34(sliced25) or type(sliced25.Uid) == "string" and string.sub(sliced25.Uid, 1, #str3) == str3 then
						table.insert(tbl22, sliced25)
					end
				end

				if #tbl22 ~= 0 then
					sliced24 = tbl22
				end

				local sliced25, sliced26 = slicedfn32(sliced24)

				if not sliced25 then
					tbl4.Steal.Active = false
					str2 = "No egg matches"
					return false
				end

				if sliced25.Uid == sliced21.Uid then
					return (slicedfn58("Target is the closest egg, taking it"))
				end
				local sliced27, sliced28 = slicedfn35(sliced25)
				local sliced29

				if sliced28 and sliced23 then
					local sliced30, sliced31, sliced32 = ipairs(sliced24)
					local huge3 = math.huge
					sliced29 = sliced25

					for _, sliced33 in sliced30, sliced31, sliced32 do
						local position2 = typeof(sliced33.CFrame) == "CFrame" and sliced33.CFrame.Position or nil

						if sliced33.Uid ~= sliced21.Uid and sliced33.AreaId == sliced25.AreaId and position2 then
							local magnitude = (position2 - sliced23.Position).Magnitude

							if slicedn12 < (position2 - sliced28).Magnitude then
								magnitude += slicedn12
							end

							if magnitude < huge3 then
								huge3 = magnitude
								sliced29 = sliced33
							end
						end
					end
				else
					sliced29 = sliced25
				end

				str2 = string.format("Sleeping guard egg %d studs away", math.floor(sliced26 + 0.5))

				if not sliced29 then
					tbl4.Steal.Active = false
					str2 = "No egg matches"
					return false
				end

				local sliced30, sliced31 = slicedfn45(sliced29, sliced19, false, tbl21[1])
				if not sliced30 then
					tbl4.Steal.Active = false
					return false
				end
				local uid2 = nil
				local uid3 = sliced21.Uid
				local slicedn21 = 0

				while true do
					if sliced31 and not slicedfn13(sliced19) then
						str2 = "Holding for the guard hit"

						if slicedfn43(sliced19, sliced31, function(arg)
							if not uid2 and tbl20.Uid and tbl20.Freed then
								uid2 = tbl20.Uid
								arg.Destination = tbl20.Freed + Vector3.new(0, 3, 0)
								local sliced32 = tbl20
								tbl20.Uid = nil
								sliced32.Freed = nil
								str2 = "Best egg fell, jumping to it instead"
							end
						end) then
							slicedn21 += 1

							if uid2 then
								uid3 = uid2
								slicedfn50(sliced19, uid2)
								break
							else
								local sliced32 = tbl21[slicedn21]
								local sliced33
								sliced33, sliced31 = slicedfn45(sliced32, sliced19, true, tbl21[slicedn21 + 1])

								if sliced33 then
									if sliced32 and type(sliced32.Uid) == "string" then
										uid3 = sliced32.Uid
									end

									continue
								end
							end
						end
					end

					break
				end

				if not slicedfn29(uid3, sliced19) then
					local sliced32 = str2
					slicedfn25()
					tbl4.Steal.Active = false
					tbl4.Steal.LastFinishedAt = os.clock()
					str2 = sliced32
					return true
				end

				local sliced32 = slicedfn54(sliced19)
				slicedfn25()
				tbl4.Steal.Active = false
				tbl4.Steal.LastFinishedAt = os.clock()
				str2 = sliced32 and "Delivered" or "Run ended"
				return true
			end

			local eggState = tbl.EggState

			if type(eggState) == "table" then
				for _, sliced19 in ipairs({ "FieldRefreshed", "FieldShifted", "FieldGone", "SnapshotRefreshed" }) do
					local sliced20 = eggState[sliced19]

					if type(sliced20) == "table" and type(sliced20.Connect) == "function" then
						local ok, result = pcall(sliced20.Connect, sliced20, function()
							tbl3.Wake()
						end)

						if ok and result then
							slicedfn4(function()
								pcall(function()
									result:Disconnect()
								end)
							end)
						end
					end
				end
			end

			tbl3.Add(function()
				local flag4 = nil

				if sliced15 then
					flag4 = type(sliced15.Set) == "function"
				end

				if flag4 then
					pcall(sliced15.Set, nil, str2)
				end

				local flag5 = nil

				if sliced16 then
					flag5 = type(sliced16.Set) == "function"
				end

				if flag5 then
					pcall(sliced16.Set, nil, str)
				end

				if not tbl4.Toggle(sliced14, false) then
					return false
				end
				local sliced19, sliced20, sliced21 = slicedfn14()

				if sliced19 then
					if sliced20 == "night" then
						slicedfn16()
					end

					tbl4.Movement.StealFirst = true
					tbl4.Steal.Wanted = false

					if flag2 then
						slicedn5 += 1
						tbl4.Steal.Active = false
						slicedfn25()
						tbl4.StopWalking()
					end

					local slicedn21 = math.max(0, math.ceil(sliced19 - sliced21))

					if sliced20 == "wall" then
						str2 = string.format("Field wall up, %ds", slicedn21)
					else
						str2 = string.format("Night, going again in %ds", slicedn21)
					end

					return false
				end

				if sliced17 and slicedn8 == math.huge then
					slicedn8 = os.clock() + slicedn7
				end

				if flag2 then
					return true
				end

				if slicedfn17() then
					str2 = "Night over, waiting for the field to reset"
					tbl3.Wake()
					return false
				end

				local stealFirst = tbl4.Movement.StealFirst
				local owner = tbl4.Movement.Owner
				local flag6 = tbl4.Movement.PlaceWanted and not stealFirst

				if not flag6 then
					flag6 = owner ~= nil and owner ~= "steal" and owner ~= "treadmill" and owner ~= "scramble"
				end

				if flag6 then
					if os.clock() >= slicedn19 then
						slicedn19 = os.clock() + slicedn17
						local ok, result = pcall(slicedfn19, false, false)
						ok = ok and type(result) == "table" and result[1] ~= nil
						tbl4.Steal.Wanted = ok

						if ok then
							tbl4.Movement.StealFirst = true
						end
					end

					if tbl4.Steal.Wanted then
						local tostring = tostring
						owner = owner or "Auto Place"
						str2 = "Egg found, waiting for " .. tostring(owner) .. " to stop"
					else
						str2 = "Waiting for " .. tostring(owner or "Auto Place")
					end

					return true
				end

				if os.clock() < slicedn20 then
					return true
				end
				tbl4.Movement.StealFirst = false
				flag2 = true

				task.spawn(function()
					local ok = pcall(slicedfn57)

					if flag3 then
						flag3 = false
						tbl4.ReleaseBelt()
					end

					if not ok then
						slicedfn25()
						tbl4.Steal.Active = false
					end

					local sliced22 = uid
					uid = nil
					local sliced23 = sliced22 and tbl14[sliced22]

					if sliced23 and sliced23.Once then
						tbl14[sliced22] = nil
					end

					local sliced24 = tbl20
					local sliced25 = tbl20
					tbl20.Uid = nil
					sliced24.Freed = nil
					sliced25.Token = nil

					if str2 == "Delivered" and not tbl4.IsNight() then
						tbl4.Movement.StealFirst = true
					end

					if not tbl4.Steal.Wanted then
						slicedn20 = os.clock() + slicedn18
					end

					tbl4.ReleaseMovement("steal")
					flag2 = false
					tbl3.Wake()
				end)

				return true
			end)
		end

		sliced14 = sliced5

		slicedfn12 = function()
			slicedn5 += 1
			table.clear(tbl18)
			tbl4.Steal.Active = false
			tbl4.Steal.Wanted = false
			local sliced19 = tbl4.Toggle(sliced14, false)
			tbl4.Shield("steal", sliced19)

			if not sliced19 then
				tbl4.Movement.StealFirst = false
				table.clear(tbl14)
				table.clear(tbl15)
				table.clear(tbl16)
			end

			slicedfn25()
			tbl4.StopWalking()
			tbl3.Wake()
		end

		do
			local function slicedfn36()
				slicedn5 += 1
				tbl4.Steal.Active = false
				slicedfn25()
				tbl4.StopWalking()
			end

			local function slicedfn37()
				if tbl4.Toggle(sliced14, false) then
					return true
				end

				if sliced14 and type(sliced14.Set) == "function" then
					pcall(sliced14.Set, sliced14, true)
				end

				return false
			end

			tbl4.CancelSteal = function(arg)
				if type(arg) ~= "string" then
					return
				end
				tbl14[arg] = nil
				tbl15[arg] = nil
				tbl16[arg] = true

				if flag2 and uid == arg then
					slicedfn36()
				end

				tbl3.Wake()
			end

			tbl4.StealQueue = function()
				local tbl19 = {}

				for k in pairs(tbl14) do
					table.insert(tbl19, k)
				end

				table.sort(tbl19, function(arg, arg2)
					local at = tbl14[arg].At
					local at2 = tbl14[arg2].At
					if at ~= at2 then
						return at < at2
					end
					return arg < arg2
				end)

				return tbl19
			end

			tbl4.PrioritizeSteal = function(arg)
				if type(arg) ~= "string" or slicedfn15() then
					return
				end
				local slicedn13 = 0

				for _, sliced19 in pairs(tbl14) do
					if sliced19.At < slicedn13 then
						slicedn13 = sliced19.At
					end
				end

				tbl14[arg] = { At = slicedn13 - 1, Once = false }
				tbl16[arg] = nil
				tbl18[arg] = nil

				if slicedfn37() and flag2 and not tbl4.Steal.Carrying and uid ~= arg then
					slicedfn36()
				end

				tbl3.Wake()
			end

			tbl4.MoveInPlan = function(arg, arg2)
				if type(arg) ~= "string" or arg2 ~= -1 and arg2 ~= 1 or slicedfn15() then
					return
				end
				local sliced19 = tbl4.StealPlan()
				local sliced20 = table.find(sliced19, arg)
				local slicedn13 = sliced20 and sliced20 + arg2
				if not slicedn13 or slicedn13 < 1 or slicedn13 > #sliced19 then
					return
				end
				table.remove(sliced19, sliced20)
				table.insert(sliced19, slicedn13, arg)
				local slicedn14 = math.max(sliced20, slicedn13)

				for i, sliced21 in ipairs(sliced19) do
					if i <= slicedn14 or tbl14[sliced21] then
						local sliced22 = tbl14[sliced21]

						if sliced22 then
							sliced22.At = i
						else
							tbl14[sliced21] = { At = i, Once = false }
						end

						tbl16[sliced21] = nil
					end
				end

				if flag2 and not tbl4.Steal.Carrying and uid and sliced19[1] ~= uid then
					slicedfn36()
				end

				tbl3.Wake()
			end

			tbl4.StealPlan = function()
				if not tbl4.Toggle(sliced14, false) or tbl4.IsNight() then
					return {}, nil
				end
				local tbl19 = {}

				if uid then
					table.insert(tbl19, uid)
				end

				local ok, result = pcall(slicedfn19, false, true)

				if ok and type(result) == "table" then
					for _, sliced19 in ipairs(result) do
						if sliced19.Uid ~= uid then
							table.insert(tbl19, sliced19.Uid)
						end
					end
				end

				return tbl19, uid
			end

			tbl4.SetPriority = function(arg, arg2)
				if arg2 then
					tbl4.PrioritizeSteal(arg)
				else
					tbl4.CancelSteal(arg)
				end
			end

			tbl4.ResortSteal = function()
				if flag2 and not tbl4.Steal.Carrying and uid and not tbl14[uid] then
					local ok, result = pcall(slicedfn19, false, true)

					if ok and type(result) == "table" then
						local sliced19 = nil

						for _, sliced20 in ipairs(result) do
							if sliced20.State ~= "Carried" then
								sliced19 = sliced20
								break
							else
								sliced19 = nil
							end
						end

						if not sliced19 or sliced19.Uid ~= uid then
							slicedfn36()
						end
					end
				end

				tbl3.Wake()
			end

			tbl4.StealNow = function(arg, arg2)
				if type(arg) ~= "string" or slicedfn15() then
					return
				end

				if not tbl14[arg] then
					local slicedn13 = 0

					for _, sliced19 in pairs(tbl14) do
						if slicedn13 < sliced19.At then
							slicedn13 = sliced19.At
						end
					end

					tbl14[arg] = { At = slicedn13 + 1, Once = arg2 == true }
				end

				tbl16[arg] = nil
				tbl18[arg] = nil
				local flag3 = slicedfn37() and flag2 and not tbl4.Steal.Carrying and uid ~= arg

				if flag3 then
					flag3 = not (uid and tbl14[uid])
				end

				if flag3 then
					slicedfn36()
				end

				tbl3.Wake()
			end
		end

		slicedfn4(function()
			tbl4.GodMode(false)
			tbl4.ReleaseMovement("steal")
			slicedfn25()
		end)

		tbl4.UiQueue = {}

		tbl4.UiDefer = function(arg)
			table.insert(tbl4.UiQueue, arg)
		end

		tbl4.Notify = function(arg, arg2)
			if type(v) == "table" and type(v.Notify) == "function" then
				pcall(v.Notify, arg, arg2, 5)
			end
		end

		local connection = RunService.Heartbeat:Connect(function()
			local uiQueue = tbl4.UiQueue
			if #uiQueue == 0 then
				return
			end
			tbl4.UiQueue = {}

			for _, sliced19 in ipairs(uiQueue) do
				pcall(sliced19)
			end
		end)

		slicedfn4(function()
			pcall(function()
				connection:Disconnect()
			end)
		end)

		tbl4.Rift = { Requirements = {}, At = 0, Busy = false, Next = 0, Handles = {}, Restart = {} }

		tbl4.RiftOn = function(arg)
			local sliced19 = tbl4.Rift.Handles[arg]
			return sliced19 ~= nil and tbl4.Toggle(sliced19, false) == true
		end

		do
			local slicedn13 = 8

			local function slicedfn36(arg)
				local directory = tbl.Assets and tbl.Assets.Directory
				local flag3 = type(directory) == "table" and directory[tostring(arg)] or nil
				return type(flag3) == "table" and flag3 or nil
			end

			tbl4.EggRarity = function(arg)
				local rarity = slicedfn36(arg.AssetCategory)
				rarity = rarity and rarity.Rarity or nil
				local flag3 = type(rarity) == "table"

				if flag3 then
					flag3 = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				return flag3 or 0
			end

			tbl4.EggIncome = function(arg)
				local slicedn14 = slicedfn36(arg.AssetCategory)
				slicedn14 = slicedn14 and tonumber(slicedn14.EarningRate) or 0
				local slicedn15 = tonumber(arg.AssetScale) or 0
				if slicedn15 <= 0 then
					return 0
				end
				local slicedn16 = slicedn15 > 5 and (slicedn15 / 5) ^ 1.2 * 19.637875755794113 or slicedn15 ^ 1.85
				local mutations = tbl.Mutations
				local flag3 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn17 = 1

				if flag3 then
					local ok
					ok, slicedn17 = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
					local flag4 = ok and type(slicedn17) == "number"
					local slicedn18 = 1

					if not flag4 then
						slicedn17 = slicedn18
					end
				end

				return slicedn14 * slicedn16 * slicedn17
			end

			tbl4.RiftShortfall = function()
				local tbl19 = {}

				for _, requirement in ipairs(tbl4.Rift.Requirements) do
					tbl19[requirement] = (tbl19[requirement] or 0) + 1
				end

				if next(tbl19) == nil then
					return tbl19
				end
				local save2 = tbl.Save
				local flag3 = type(save2) == "table" and type(save2.Get) == "function"
				local result = nil

				if flag3 then
					local ok
					ok, result = pcall(save2.Get)
					result = ok and type(result) == "table" and result or nil
				end

				if not result then
					return {}
				end
				local tbl20 = {}
				local pairs = pairs
				local equippedAssets = result.EquippedAssets or {}

				for _, equippedAsset in pairs(equippedAssets) do
					tbl20[equippedAsset] = true
				end

				local sliced20 = pairs
				local inventory = result.Inventory or {}

				for k, sliced21 in sliced20(inventory) do
					local str3 = type(sliced21) == "table" and tostring(sliced21.Category) or nil
					local flag4

					if str3 then
						flag4 = (tbl19[str3] or 0) > 0
					else
						flag4 = str3
					end

					flag4 = flag4 and sliced21.InFuse ~= true and sliced21.IsFavorite ~= true and not tbl20[k]

					if flag4 then
						tbl19[str3] = tbl19[str3] - 1
					end
				end

				for k, sliced21 in pairs(tbl19) do
					if sliced21 <= 0 then
						tbl19[k] = nil
					end
				end

				return tbl19
			end

			local function slicedfn37()
				for k in pairs(tbl4.Rift.Handles) do
					if tbl4.RiftOn(k) then
						return true
					end
				end

				return false
			end

			tbl3.Add(function()
				local rift = tbl4.Rift
				local busy = rift.Busy

				if not busy then
					local next_ = rift.Next
					busy = os.clock() < next_
				end

				if busy or not slicedfn37() then
					return false
				end
				rift.Busy = true
				rift.Next = os.clock() + slicedn13

				task.spawn(function()
					local rfScrambleTradeInAskState = networking:FindFirstChild("RF/ScrambleTradeIn/AskState")

					if rfScrambleTradeInAskState and rfScrambleTradeInAskState:IsA("RemoteFunction") then
						local ok, result = pcall(rfScrambleTradeInAskState.InvokeServer, rfScrambleTradeInAskState)

						if ok and type(result) == "table" then
							local requirements = {}

							if result.Unlocked == true and type(result.Requirements) == "table" then
								for _, requirement in ipairs(result.Requirements) do
									table.insert(requirements, tostring(requirement))
								end
							end

							rift.Requirements = requirements
							rift.At = os.clock()
						end
					end

					rift.Busy = false
					tbl3.Wake()
				end)

				return false
			end)
		end

		local tbl19 = { "Always", "Steal Idle", "After Steal", "Night Only" }
		local tbl20 = { "Biggest Size", "Highest Value", "Smallest Size", "Backpack Order" }
		local sliced19 = tbl19[1]
		local sliced20 = tbl20[2]
		local tbl21 = {}
		local tbl22 = {}
		local slicedn13 = 0

		do
			local function slicedfn36()
				if type(tbl4.PlaceEggRefresh) == "function" then
					tbl4.PlaceEggRefresh()
				end
			end

			local function slicedfn37(arg)
				local tbl23 = {}

				if type(arg) == "table" then
					for k, sliced21 in pairs(arg) do
						k = sliced21 == true and type(k) == "string" and k or type(sliced21) == "string" and sliced21 or nil

						if k then
							table.insert(tbl23, k)
						end
					end
				end

				return tbl23
			end

			tbl4.PlaceEggStatusRow = sliced9:CreateText({ Name = "Pen Status", Text = "Pen status unknown" })

			tbl4.PlaceEggHandle = sliced9:CreateToggle({
				Name = "Auto Place Egg",
				Default = false,
				Callback = function()
					if type(tbl4.PlaceEggRestart) == "function" then
						tbl4.PlaceEggRestart()
					end
				end,
			})

			local placeEggHandle = tbl4.PlaceEggHandle

			sliced9:CreateDropdown({
				Name = "Place Egg Rule",
				Options = tbl19,
				Default = tbl19[1],
				SubOf = placeEggHandle,
				Callback = function(arg)
					if table.find(tbl19, arg) then
						sliced19 = arg
					end
				end,
			})

			sliced9:CreateDropdown({
				Name = "Place Egg Order",
				Options = tbl20,
				Default = tbl20[2],
				SubOf = placeEggHandle,
				Callback = function(arg)
					if table.find(tbl20, arg) then
						sliced20 = arg
					end
				end,
			})

			local tbl23 = {}

			for i = 2, #tbl8 do
				table.insert(tbl23, tbl8[i])
			end

			if #tbl23 > 0 then
				slicedfn6(sliced9:CreateMultiDropdown({
					Name = "Place Rarities",
					Note = "Only place eggs of the picked rarities (empty = all)",
					Options = tbl23,
					Default = {},
					SubOf = placeEggHandle,
					Callback = function(arg)
						local tbl24 = {}

						for _, sliced21 in ipairs(slicedfn37(arg)) do
							local sliced22 = tbl9[sliced21]

							if sliced22 and sliced22 > 0 then
								tbl24[sliced22] = true
							end
						end

						tbl21 = tbl24
						slicedfn36()
					end,
				}))
			end

			local tbl24 = {}
			local tbl25 = {}
			local directory = tbl.Assets and tbl.Assets.Directory
			local tbl26 = {}

			if type(directory) == "table" then
				for k, sliced21 in pairs(directory) do
					local rarity = type(sliced21) == "table" and sliced21.Rarity or nil
					local rarity2 = type(rarity) == "table"

					if rarity2 then
						rarity2 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					rarity2 = rarity2 or nil

					if rarity2 then
						local insert = table.insert
						local tbl27 = { Category = tostring(k) }
						local tostring = tostring
						k = sliced21.DisplayName or k
						tbl27.Name = tostring(k)
						tbl27.Rarity = rarity2
						tbl27.RarityName = tostring(rarity.DisplayName or rarity._id or rarity2)
						insert(tbl26, tbl27)
					end
				end
			end

			table.sort(tbl26, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity > arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced21 in ipairs(tbl26) do
				local str3 = string.format("%s [%s]", sliced21.Name, sliced21.RarityName)

				if tbl25[str3] then
					str3 = string.format("%s [%s] (%s)", sliced21.Name, sliced21.RarityName, sliced21.Category)
				end

				table.insert(tbl24, str3)
				tbl25[str3] = sliced21.Category
			end

			if #tbl24 > 0 then
				slicedfn6(sliced9:CreateMultiDropdown({
					Name = "Place Specific Eggs",
					Note = "Only place these eggs (empty = all)",
					Options = tbl24,
					Default = {},
					SubOf = placeEggHandle,
					Callback = function(arg)
						local tbl27 = {}

						for _, sliced21 in ipairs(slicedfn37(arg)) do
							if tbl25[sliced21] then
								tbl27[tbl25[sliced21]] = true
							end
						end

						tbl22 = tbl27
						slicedfn36()
					end,
				}))
			end

			local tbl27 = {
				["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
				["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
				["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
			}

			local slicedn14 = 0
			local str3 = "M/s"

			local function slicedfn38(arg, arg2)
				if arg ~= nil then
					slicedn14 = math.max(0, math.floor(tonumber(arg) or slicedn14))
				end

				if arg2 ~= nil then
					str3 = tostring(arg2)
				end

				slicedn13 = slicedn14 * (tbl27[str3] or tbl27["M/s"]).Mult
			end

			slicedfn5(sliced9, {
				Name = "Min Place Value",
				Note = "Skip eggs worth less than this (0 = off)",
				SubOf = placeEggHandle,
				Legacy = "Place Min Value",
				SectionName = "Auto Place Egg",
				OnRaw = function(arg)
					slicedfn38(math.floor(arg / 1000), "K/s")
				end,
			})
		end

		do
			local slicedn14 = 5
			local slicedn15 = 26
			local slicedn16 = 6
			local slicedn17 = 8
			local slicedn18 = 0
			local slicedn19 = 30
			local slicedn20 = 12
			local placeEggHandle = nil
			local placeEggStatusRow = nil
			local str3 = "Pen status unknown"
			local flag3 = false
			local tbl23 = {}
			local slicedn21 = 0
			local sliced21 = nil
			local slicedn22 = 30

			local function slicedfn36(arg, arg2)
				local sliced22 = networking:FindFirstChild(arg)
				if not sliced22 or not sliced22:IsA("RemoteFunction") then
					return false, nil
				end
				return pcall(sliced22.InvokeServer, sliced22, arg2)
			end

			local function slicedfn37(arg)
				local directory = tbl.Assets and tbl.Assets.Directory
				local flag4 = type(directory) == "table" and directory[tostring(arg.AssetCategory)] or nil
				return type(flag4) == "table" and flag4 or nil
			end

			local function slicedfn38(arg)
				local rarity = slicedfn37(arg)
				rarity = rarity and rarity.Rarity or nil
				local flag4 = type(rarity) == "table"
				local num

				if flag4 then
					num = tonumber(rarity.RarityNumber or rarity.Rank)
				else
					num = flag4
				end

				return num or 0
			end

			local function slicedfn39(arg)
				local slicedn23 = slicedfn37(arg)
				slicedn23 = slicedn23 and tonumber(slicedn23.EarningRate) or 0
				local slicedn24 = tonumber(arg.AssetScale) or 0
				if slicedn24 <= 0 then
					return 0
				end
				local slicedn25 = slicedn24 > 5 and (slicedn24 / 5) ^ 1.2 * 19.637875755794113 or slicedn24 ^ 1.85
				local mutations = tbl.Mutations
				local flag4 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn26 = 1

				if flag4 then
					local ok
					ok, slicedn26 = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
					ok = ok and type(slicedn26) == "number"
					local slicedn27 = 1

					if not ok then
						slicedn26 = slicedn27
					end
				end

				return slicedn23 * slicedn25 * slicedn26
			end

			local function slicedfn40()
				local tbl24 = {}
				local backpack = localPlayer:FindFirstChildOfClass("Backpack")
				if not backpack then
					return tbl24
				end
				local slicedn23 = 0

				for _, child in ipairs(backpack:GetChildren()) do
					local attribute = child:GetAttribute("UID")

					if type(attribute) == "string" then
						slicedn23 += 1
						tbl24[attribute] = slicedn23
					end
				end

				return tbl24
			end

			local function slicedfn41()
				local eggState = tbl.EggState
				if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
					return {}
				end
				local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
				if not ok or type(result) ~= "table" then
					return {}
				end
				local sliced22 = slicedfn40()
				local tbl24 = {}

				if tbl4.RiftOn("Place") then
					tbl24 = tbl4.RiftShortfall()

					for _, sliced23 in pairs(result) do
						if type(sliced23) == "table" and sliced23.Placement ~= nil then
							local str4 = tostring(sliced23.AssetCategory)

							if (tbl24[str4] or 0) > 0 then
								tbl24[str4] = tbl24[str4] - 1
							end
						end
					end
				end

				local tbl25 = {}

				for k, sliced23 in pairs(result) do
					if type(sliced23) == "table" and sliced23.Placement == nil and not tbl23[k] then
						local sliced24 = slicedfn39(sliced23)
						local str4 = tostring(sliced23.AssetCategory)
						local flag4 = next(tbl21) == nil or tbl21[slicedfn38(sliced23)] == true
						local flag5 = next(tbl22) == nil or tbl22[str4] == true
						local flag6 = slicedn13 <= 0 or sliced24 >= slicedn13
						local flag7 = (tbl24[str4] or 0) > 0

						if flag7 then
							tbl24[str4] = tbl24[str4] - 1
						end

						if flag7 then
							flag6 = flag7
						else
							flag6 = flag4 and flag5 and flag6
						end

						if flag6 then
							table.insert(tbl25, {
								Uid = k,
								Scale = tonumber(sliced23.AssetScale) or 0,
								Income = sliced24,
								Slot = sliced22[k] or math.huge,
								Rift = flag7,
							})
						end
					end
				end

				table.sort(tbl25, function(arg, arg2)
					if arg.Rift ~= arg2.Rift then
						return arg.Rift
					end

					if sliced20 == tbl20[2] and arg.Income ~= arg2.Income then
						return arg.Income > arg2.Income
					end

					if sliced20 == tbl20[3] and arg.Scale ~= arg2.Scale then
						return arg.Scale < arg2.Scale
					end

					if sliced20 == tbl20[4] and arg.Slot ~= arg2.Slot then
						return arg.Slot < arg2.Slot
					end
					return arg.Scale > arg2.Scale
				end)

				return tbl25
			end

			local function slicedfn42(arg)
				if arg == 0 then
					return false
				end
				local steal = tbl4.Steal
				if sliced19 == tbl19[2] then
					return not steal.Active and not steal.Carrying
				end

				if sliced19 == tbl19[3] then
					local flag4 = steal.LastFinishedAt > 0

					if flag4 then
						local lastFinishedAt = steal.LastFinishedAt
						flag4 = os.clock() - lastFinishedAt <= slicedn20
					end

					return flag4
				end

				if sliced19 == tbl19[4] then
					return tbl4.IsNight()
				end
				return true
			end

			local function slicedfn43()
				local eggState = tbl.EggState
				local flag4 = type(eggState) == "table" and type(eggState.ReadOwnerEggs) == "function"
				local slicedn23 = 0

				if flag4 then
					local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)

					if ok and type(result) == "table" then
						for _, sliced22 in pairs(result) do
							if type(sliced22) == "table" and sliced22.Placement ~= nil then
								slicedn23 += 1
							end
						end
					end
				end

				local save2 = tbl.Save
				local flag5 = type(save2) == "table" and type(save2.Get) == "function"
				local result = nil

				if flag5 then
					local ok
					ok, result = pcall(save2.Get)
					result = ok and type(result) == "table" and result or nil
				end

				local flag6 = result and type(result.EquippedAssets) == "table"
				local slicedn24 = 0

				if flag6 then
					for k in pairs(result.EquippedAssets) do
						slicedn24 += 1
					end
				end

				local sliced22 = slicedfn2(function()
					return ReplicatedStorage.Data.Bases
				end)

				local flag7 = type(sliced22) == "table" and type(sliced22.GetAssetEquipCapacity) == "function"
				local ok = nil

				if flag7 then
					local result2
					ok, result2 = pcall(sliced22.GetAssetEquipCapacity, result and tonumber(result.BaseUpgradeLevel) or 0)
					ok = ok and tonumber(result2) or nil
				end

				if not ok then
					local rfPenRosterAskWearLimit = networking:FindFirstChild("RF/PenRoster/AskWearLimit")

					if rfPenRosterAskWearLimit and rfPenRosterAskWearLimit:IsA("RemoteFunction") then
						local result2
						ok, result2 = pcall(rfPenRosterAskWearLimit.InvokeServer, rfPenRosterAskWearLimit)
						ok = ok and tonumber(result2) or nil
					end
				end

				ok = ok or 0
				return ok - slicedn23 - slicedn24, ok, slicedn23, slicedn24
			end

			local slicedn23 = -0.5
			local slicedn24 = -24

			local function slicedfn44()
				local eggState = tbl.EggState
				local tbl24 = {}
				if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
					return tbl24
				end
				local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
				if not ok or type(result) ~= "table" then
					return tbl24
				end

				for _, sliced22 in pairs(result) do
					local placement = type(sliced22) == "table" and sliced22.Placement or nil
					local localCFrame = type(placement) == "table" and placement.LocalCFrame or nil

					if typeof(localCFrame) == "CFrame" then
						table.insert(tbl24, Vector2.new(localCFrame.Position.X, localCFrame.Position.Z))
					end
				end

				return tbl24
			end

			local sliced22 = Random.new()

			local function slicedfn45(arg)
				local tbl24 = {}

				for i = slicedn24, 8, 4 do
					for i2 = 4, 30, 4 do
						local vector2 = Vector2.new(i, i2)
						local flag4 = true

						for _, sliced23 in ipairs(arg) do
							if (sliced23 - vector2).Magnitude < slicedn14 then
								flag4 = false
								break
							end
						end

						if flag4 then
							table.insert(tbl24, CFrame.new(i, slicedn23, i2))
						end
					end
				end

				for i = #tbl24, 2, -1 do
					local sliced23 = sliced22:NextInteger(1, i)
					local sliced24 = tbl24[i]
					tbl24[i] = tbl24[sliced23]
					tbl24[sliced23] = sliced24
				end

				return tbl24
			end

			local function slicedfn46()
				local sliced23, sliced24, sliced25, sliced26 = slicedfn43()
				local eggState = tbl.EggState
				local flag4 = type(eggState) == "table" and type(eggState.ReadOwnerEggs) == "function"
				local slicedn25 = 0

				if flag4 then
					local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)

					if ok and type(result) == "table" then
						for _, sliced27 in pairs(result) do
							if type(sliced27) == "table" and sliced27.Placement == nil then
								slicedn25 += 1
							end
						end
					end
				end

				str3 = string.format("Eggs placed %d/%d  -  %d/%d pets equipped, %d in bag", sliced25, 30, sliced26, sliced24, slicedn25)
				return sliced23, sliced25
			end

			local function slicedfn47(arg, arg2)
				local sliced23 = tbl4.Root()
				if not sliced23 then
					return false
				end
				local position = sliced23.Position
				local slicedn25 = (arg - position).Magnitude / math.max(400, 1) + 3
				local flag4 = nil
				local slicedn26 = 0

				local connection2 = RunService.Heartbeat:Connect(function(deltaTime)
					if flag4 ~= nil or tbl4.AntiGuard.Busy then
						return
					end
					slicedn26 += deltaTime
					local sliced24 = tbl4.Root()
					if not sliced24 or arg2() or slicedn26 > slicedn25 then
						flag4 = false
						return
					end

					if (sliced24.Position - position).Magnitude > 6 then
						position = sliced24.Position
					end

					local slicedn27 = arg - position
					local slicedn28 = slicedn4 * deltaTime
					local flag5 = slicedn27.Magnitude <= math.max(slicedn28, 0.05)
					position = flag5 and arg or position + slicedn27.Unit * slicedn28
					local vector = Vector3.new(slicedn27.X, 0, slicedn27.Z)
					local cframe = vector.Magnitude > 0.05 and CFrame.lookAt(Vector3.zero, vector.Unit) or sliced24.CFrame.Rotation

					pcall(function()
						sliced24.CFrame = CFrame.new(position) * cframe
						sliced24.AssemblyLinearVelocity = Vector3.zero
						sliced24.AssemblyAngularVelocity = Vector3.zero
					end)

					if flag5 then
						flag4 = true
					end
				end)

				while flag4 == nil do
					RunService.Heartbeat:Wait()
				end

				connection2:Disconnect()
				return flag4
			end

			local function slicedfn48()
				local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
				world = world and world:FindFirstChild("Areas")
				world = world and world:FindFirstChild("SeparationLine")
				return world and world:IsA("BasePart") and world.Position.X or 552
			end

			local slicedfn49 = nil

			local function slicedfn50(arg)
				local sliced23 = tbl4.Root()
				if not sliced23 or type(tbl4.StealHome) ~= "function" then
					return nil
				end
				local sliced24 = slicedfn48()
				if sliced23.Position.X < sliced24 == (arg.X < sliced24) then
					return nil
				end
				local ok, result = pcall(tbl4.StealHome)
				if not ok or typeof(result) ~= "Vector3" then
					return nil
				end

				if (result - arg).Magnitude <= 12 or (sliced23.Position - result).Magnitude <= 12 then
					return nil
				end
				return result
			end

			slicedfn49 = function(arg, arg2, arg3, arg4)
				local sliced23 = tbl4.Root()
				if not sliced23 then
					return false
				end

				if not arg4 then
					local sliced24 = slicedfn50(arg)
					if sliced24 and not slicedfn49(sliced24, arg2, arg3, true) then
						return false
					end

					if arg2 and arg2() then
						return false
					end
					sliced23 = tbl4.Root()
					if not sliced23 then
						return false
					end
				end

				tbl4.Shield(arg3 or "place", true)
				tbl4.Driving = tbl4.Driving + 1
				task.wait(0.2)
				local slicedn25 = arg + Vector3.new(0, 3, 0)
				local slicedn26 = math.max(sliced23.Position.Y, slicedn25.Y) + slicedn22

				local ok, result = pcall(function()
					return slicedfn47(Vector3.new(sliced23.Position.X, slicedn26, sliced23.Position.Z), arg2) and slicedfn47(Vector3.new(slicedn25.X, slicedn26, slicedn25.Z), arg2) and slicedfn47(slicedn25, arg2)
				end)

				ok = ok and result == true
				tbl4.Driving = math.max(0, tbl4.Driving - 1)
				tbl4.Shield(arg3 or "place", false)
				return ok
			end

			tbl4.FlyTo = function(arg, arg2, arg3)
				return slicedfn49(arg, arg2, arg3 or "fly")
			end

			local function slicedfn51()
				local eggState = tbl.EggState
				if type(eggState) ~= "table" or type(eggState.PlantEgg) ~= "function" then
					return false
				end
				local sliced23 = slicedfn41()
				if not slicedfn42(#sliced23) then
					return false
				end
				slicedfn46()
				local sliced24, sliced25, sliced26 = slicedfn43()
				local slicedn25 = slicedn19 - (tonumber(sliced26) or 0)
				if slicedn25 <= 0 then
					return false
				end
				local sliced27 = tbl4.PenAnchor()
				if not sliced27 then
					return false
				end
				tbl4.Movement.PlaceWanted = true
				if not tbl4.ClaimMovement("place") then
					return "waiting"
				end
				local sliced28 = slicedn21

				local function slicedfn52()
					if sliced28 ~= slicedn21 or not tbl4.Toggle(placeEggHandle, false) then
						return true
					end

					if tbl4.IsNight() then
						return false
					end
					return sliced19 == tbl19[4] or tbl4.Movement.StealFirst
				end

				if tbl4.Treadmill.Riding or tbl4.OnBelt() then
					tbl4.ExitBelt()
				end

				local function slicedfn53()
					tbl4.HoldBelt()
					local ok, result = pcall(slicedfn49, sliced27, slicedfn52)
					tbl4.ReleaseBelt()
					return ok and result and true or false
				end

				if slicedn15 < tbl4.DistanceTo(sliced27) then
					str3 = "Flying to the pen"

					if not slicedfn53() then
						tbl4.LeaveBelt()
						slicedn18 = os.clock() + slicedn16
						return false
					end
				end

				tbl4.LeaveBelt()
				if slicedfn52() then
					return false
				end

				local function slicedfn54()
					if tbl4.DistanceTo(sliced27) <= slicedn15 then
						return true
					end

					if slicedfn52() then
						return false
					end
					str3 = "Pen out of reach, flying back"
					return slicedfn53() and tbl4.DistanceTo(sliced27) <= slicedn15
				end

				if not slicedfn54() then
					str3 = "Could not reach the pen, trying again soon"
					slicedn18 = os.clock() + slicedn16
					return false
				end

				local sliced29 = slicedfn44()
				local slicedn26 = 0
				local slicedn27 = 0

				for _, sliced30 in ipairs(sliced23) do
					if not (slicedn26 >= slicedn25 or slicedfn52()) then
						if not slicedfn54() then
							str3 = "Pen out of reach, stopping this pass"
							break
						else
							local ok, result = pcall(eggState.WearEggTool, sliced30.Uid)

							if ok and result ~= false then
								task.wait(0.15)
								local slicedn28 = 0
								local flag4 = false

								for _, sliced31 in ipairs(slicedfn45(sliced29)) do
									if not (slicedfn52() or slicedn28 >= slicedn17) then
										slicedn28 += 1
										local AskPlaceEgg, sliced32 = slicedfn36("RF/EggWorld/AskPlaceEgg", { Uid = sliced30.Uid, LocalCFrame = sliced31 })

										if AskPlaceEgg and sliced32 ~= false then
											table.insert(sliced29, Vector2.new(sliced31.Position.X, sliced31.Position.Z))
											slicedn26 += 1
											flag4 = true
											break
										else
											continue
										end
									end

									break
								end

								if flag4 then
									slicedn27 = 0
									continue
								else
									tbl23[sliced30.Uid] = true
									slicedn27 += 1
									if not (slicedn27 >= 2) then
										continue
									end
								end
							else
								tbl23[sliced30.Uid] = true
								continue
							end
						end
					end

					break
				end

				if type(eggState.DoffEggTool) == "function" then
					pcall(eggState.DoffEggTool)
				end

				if slicedn26 == 0 then
					slicedn18 = os.clock() + slicedn16
				end

				return slicedn26 > 0
			end

			tbl3.Add(function()
				local sliced23, sliced24 = slicedfn46()

				if placeEggStatusRow and type(placeEggStatusRow.Set) == "function" then
					pcall(placeEggStatusRow.Set, placeEggStatusRow, str3)
				end

				local num = tonumber(sliced24)
				local flag4 = num ~= nil and sliced21 ~= nil and num < sliced21

				if num then
					sliced21 = num
				end

				if flag4 then
					table.clear(tbl23)
				end

				if not tbl4.Toggle(placeEggHandle, false) then
					tbl4.Movement.PlaceWanted = false
					tbl4.ReleaseMovement("place")
					return false
				end

				if flag3 then
					return false
				end

				if os.clock() < slicedn18 then
					tbl4.Movement.PlaceWanted = false
					return false
				end

				if tbl4.Movement.StealFirst and not tbl4.IsNight() then
					tbl4.Movement.PlaceWanted = false
					return false
				end
				flag3 = true

				task.spawn(function()
					local ok, result = pcall(slicedfn51)

					if not (ok and result == "waiting") then
						tbl4.Movement.PlaceWanted = false
					end

					tbl4.ReleaseMovement("place")
					flag3 = false
					tbl3.Wake()
				end)

				return false
			end)

			placeEggHandle = tbl4.PlaceEggHandle
			placeEggStatusRow = tbl4.PlaceEggStatusRow

			tbl4.PlaceEggRestart = function()
				table.clear(tbl23)
				slicedn21 += 1
				tbl4.StopWalking()
				tbl3.Wake()
			end

			tbl4.PlaceEggRefresh = function()
				table.clear(tbl23)
				tbl3.Wake()
			end

			tbl4.Rift.Restart.Place = function()
				table.clear(tbl23)
				tbl3.Wake()
			end
		end

		local save2 = tbl.Save

		if type(save2) == "table" and type(save2.FieldSignal) == "function" then
			for _, sliced21 in ipairs({ "EggInventory", "EquippedAssets", "BaseUpgradeLevel" }) do
				local ok, result = pcall(save2.FieldSignal, sliced21)

				if ok and type(result) == "table" and type(result.Connect) == "function" then
					local ok2, result2 = pcall(result.Connect, result, function()
						tbl3.Wake()
					end)

					if ok2 and result2 then
						slicedfn4(function()
							pcall(function()
								result2:Disconnect()
							end)
						end)
					end
				end
			end
		end

		tbl4.Steal.HeldByMe = function()
			local carryUid = tbl4.Steal.CarryUid
			local character = localPlayer.Character
			if type(carryUid) ~= "string" or not character then
				return false
			end
			local sliced21 = workspace:FindFirstChild(carryUid)
			if not sliced21 then
				return false
			end

			for _, descendant in ipairs(sliced21:GetDescendants()) do
				if descendant:IsA("WeldConstraint") or descendant:IsA("JointInstance") then
					local ok, result, result2 = pcall(function()
						return descendant.Part0, descendant.Part1
					end)

					if ok and (result and result:IsDescendantOf(character) or result2 and result2:IsDescendantOf(character)) then
						return true
					end
				end
			end

			return false
		end

		do
			local slicedn14 = 0

			local connection2 = RunService.Heartbeat:Connect(function(deltaTime)
				slicedn14 += deltaTime
				if slicedn14 < 0.2 then
					return
				end
				slicedn14 = 0
				local steal = tbl4.Steal

				if not steal.Carrying then
					if steal.GuessedDrop then
						local ok, result = pcall(steal.HeldByMe)

						if ok and result then
							steal.GuessedDrop = false
							steal.Carrying = true
							steal.HeldSeenAt = os.clock()
						end
					end

					return
				end

				local ok, result = pcall(steal.HeldByMe)
				if not ok or result then
					steal.HeldSeenAt = os.clock()
					return
				end

				if os.clock() - (steal.HeldSeenAt or 0) > 0.8 then
					steal.Carrying = false
					steal.GuessedDrop = true
					steal.LastFinishedAt = os.clock()
					tbl3.Wake()
				end
			end)

			slicedfn4(function()
				pcall(function()
					connection2:Disconnect()
				end)
			end)
		end

		do
			local eggState = tbl.EggState
			local carryChanged = type(eggState) == "table" and eggState.CarryChanged or nil

			if type(carryChanged) == "table" and type(carryChanged.Connect) == "function" then
				local ok, result = pcall(carryChanged.Connect, carryChanged, function(arg)
					local carrying = type(arg) == "table" and arg.IsCarrying == true

					if tbl4.Steal.Carrying and not carrying then
						tbl4.Steal.LastFinishedAt = os.clock()
					end

					tbl4.Steal.GuessedDrop = false

					if carrying then
						tbl4.Steal.HeldSeenAt = os.clock()
					end

					if carrying and type(arg.Uid) == "string" then
						tbl4.Steal.CarryUid = arg.Uid
						tbl4.Steal.CarryAreaId = arg.AreaId
						local mult = tonumber(arg.SpeedMultiplier)

						if mult and mult > 0 then
							tbl4.SafeCarry.Mult = mult
							tbl4.SafeCarry.Category = arg.AssetCategory

							if arg.AssetCategory ~= nil then
								local str3 = tostring(arg.AssetCategory)
								tbl4.SafeCarry.Seen[str3] = math.min(tbl4.SafeCarry.Seen[str3] or mult, mult)
							end
						end
					end

					tbl4.Steal.Carrying = carrying
					tbl3.Wake()
				end)

				if ok and result then
					slicedfn4(function()
						pcall(function()
							result:Disconnect()
						end)
					end)
				end
			end
		end

		pcall(function()
			local reEggWorldFieldEggRedeemVerdict = networking:FindFirstChild("RE/EggWorld/FieldEggRedeemVerdict")
			local reAlertsRaise = networking:FindFirstChild("RE/Alerts/Raise")

			if reEggWorldFieldEggRedeemVerdict and reEggWorldFieldEggRedeemVerdict:IsA("RemoteEvent") then
				local connection2 = reEggWorldFieldEggRedeemVerdict.OnClientEvent:Connect(function()
					tbl4.SafeCarry.LastDelivered = os.clock()
				end)

				slicedfn4(function()
					connection2:Disconnect()
				end)
			end

			if reAlertsRaise and reAlertsRaise:IsA("RemoteEvent") then
				local connection2 = reAlertsRaise.OnClientEvent:Connect(function(arg)
					if type(arg) == "table" and type(arg.Text) == "string" and string.find(arg.Text, "Delivery failed", 1, true) then
						tbl4.SafeCarry.LastFailed = os.clock()
					end
				end)

				slicedfn4(function()
					connection2:Disconnect()
				end)
			end
		end)

		do
			local slicedn14 = 10
			local slicedn15 = 1
			local slicedn16 = 5

			local function slicedfn36(arg)
				local sliced21 = networking:FindFirstChild(arg)
				if not sliced21 or not sliced21:IsA("RemoteFunction") then
					return false, nil, nil
				end
				local ok, result, result2 = pcall(sliced21.InvokeServer, sliced21)
				return ok, result, result2
			end

			local slicedn17 = 0
			local flag3 = false

			local function slicedfn37(arg, arg2, arg3)
				if arg and arg2 ~= false then
					slicedn17 = 0
					flag3 = false
					return true
				end

				if arg and tostring(arg3) == "Already using treadmill" then
					slicedn17 = 0
					flag3 = false
					return true
				end

				if arg and tostring(arg3) == "Not grounded" and tbl4.Grounded() then
					slicedn17 += 1

					if slicedn17 >= 2 then
						slicedn17 = 0

						if not flag3 then
							flag3 = true
							pcall(tbl4.UndoSwap)
						elseif type(tbl4.RequestRespawn) == "function" then
							flag3 = false
							tbl4.RequestRespawn()
						end
					end
				end

				return false
			end

			local sliced21 = nil
			local sliced22 = nil
			local flag4 = false
			local slicedn18 = 0
			local flag5 = false
			local treadmill = tbl4.Treadmill

			local function slicedfn38()
				return tbl4.Toggle(sliced21, false)
			end

			local function slicedfn39()
				local movement = tbl4.Movement
				return movement.PlaceWanted or movement.ScrambleWanted or movement.MutationWanted or movement.FracturedWanted or movement.Owner ~= nil and movement.Owner ~= "treadmill" or tbl4.Steal.Active or tbl4.Steal.Carrying
			end

			local function slicedfn40()
				local sliced23 = slicedn18
				if slicedfn39() or not tbl4.ClaimMovement("treadmill") then
					return false
				end

				local function slicedfn41()
					return sliced23 ~= slicedn18 or not slicedfn38() or tbl4.Movement.Owner ~= "treadmill" or slicedfn39()
				end

				if tbl4.BeltHeld() then
					tbl4.ResetBelt()
				end

				local sliced24 = tbl4.Belt()
				if not sliced24 then
					return false
				end
				local slicedn19 = sliced24.Position + Vector3.new(0, sliced24.Size.Y / 2, 0)

				if tbl4.DistanceTo(slicedn19 + Vector3.new(0, 2, 0)) > slicedn14 then
					if type(tbl4.FlyTo) ~= "function" or not tbl4.FlyTo(slicedn19, slicedfn41, "treadmill") then
						return false
					end
				end

				if slicedfn41() then
					return false
				end
				treadmill.Riding = slicedfn37(slicedfn36("RF/Treadmill/AskWearStill"))
				return treadmill.Riding
			end

			tbl3.Add(function()
				if not slicedfn38() then
					if treadmill.Riding and not flag4 then
						flag4 = true

						task.spawn(function()
							pcall(tbl4.ExitBelt)
							flag4 = false
							tbl3.Wake()
						end)
					end

					return false
				end

				if flag4 or slicedfn39() then
					return false
				end

				if treadmill.Riding and tbl4.Toggle(sliced22, true) and tbl4.OnBelt() then
					if os.clock() >= (treadmill.NextCheck or 0) and not tbl4.Flying and tbl4.Grounded() then
						treadmill.NextCheck = os.clock() + slicedn16
						flag4 = true

						task.spawn(function()
							local ok, result = pcall(function()
								return slicedfn37(slicedfn36("RF/Treadmill/AskWearStill"))
							end)

							treadmill.Riding = ok and result == true

							if not treadmill.Riding then
								treadmill.NextTry = 0
							end

							flag4 = false
							tbl3.Wake()
						end)
					end

					return false
				end

				if os.clock() < (treadmill.NextTry or 0) then
					return false
				end
				treadmill.NextCheck = 0
				treadmill.NextTry = os.clock() + (treadmill.LastFailed and 3 or 4)
				flag4 = true

				task.spawn(function()
					local ok, result = pcall(slicedfn40)
					treadmill.LastFailed = not (ok and result == true)
					tbl4.ReleaseMovement("treadmill")
					flag4 = false
					tbl3.Wake()
				end)

				return false
			end)

			task.spawn(function()
				while not flag5 do
					task.wait(3)

					if not slicedfn38() and not slicedfn39() and not tbl4.Flying and tbl4.OnBelt() and tbl4.Grounded() then
						slicedfn37(slicedfn36("RF/Treadmill/AskWearStill"))
					end
				end
			end)

			task.spawn(function()
				local slicedn19 = 0

				while not flag5 do
					local sliced23 = task.wait(0.25)

					if not slicedfn38() or not treadmill.Riding or slicedfn39() then
						slicedn19 = 0
					elseif tbl4.OnBelt() then
						slicedn19 = 0
					else
						slicedn19 += sliced23

						if slicedn19 >= 1.5 then
							treadmill.Riding = false
							treadmill.NextTry = 0
							tbl3.Wake()
							slicedn19 = 0
						end
					end
				end
			end)

			task.spawn(function()
				local slicedn19 = 0
				local slicedn20 = 0
				local position = nil

				while not flag5 do
					local sliced23 = task.wait(0.25)
					slicedn19 = math.max(0, slicedn19 - sliced23)
					local flag6 = treadmill.Riding and slicedfn38() and not slicedfn39()
					local sliced24 = tbl4.Root()
					local character = localPlayer.Character
					character = character and character:FindFirstChildOfClass("Humanoid")

					if flag6 or not (tbl4.Flying or tbl4.Movement.Owner ~= nil or tbl4.Movement.PlaceWanted or character ~= nil and character.MoveDirection.Magnitude > 0.1) or not sliced24 or not tbl4.OnBelt() then
						position = sliced24 and sliced24.Position
						slicedn20 = 0
						position = position or nil
					else
						local vector = Vector3.new(sliced24.Position.X, 0, sliced24.Position.Z)
						position = position and (vector - Vector3.new(position.X, 0, position.Z)).Magnitude < 0.5

						if position then
							slicedn20 += sliced23
						else
							slicedn20 = 0
						end

						position = sliced24.Position

						if slicedn20 >= slicedn15 and slicedn19 <= 0 then
							pcall(tbl4.ExitBelt)
							slicedn19 = 1.5
							slicedn20 = 0
						end
					end
				end
			end)

			slicedfn4(function()
				flag5 = true
				treadmill.Riding = false
			end)

			sliced21 = sliced10:CreateToggle({
				Name = "Auto Treadmill",
				Default = false,
				Callback = function()
					slicedn18 += 1
					tbl4.StopWalking()
					tbl3.Wake()
				end,
			})

			sliced22 = sliced10:CreateToggle({ Name = "Stay On Treadmill", Default = true })
		end

		do
			local slicedn14 = 4
			local slicedn15 = 10
			local sliced21 = nil
			local flag3 = false
			local slicedn16 = 0
			local tbl23 = {}
			local tbl24 = { MinRarity = 0, MinIncome = 0, Eggs = {} }

			local function slicedfn36(arg, arg2)
				local sliced22 = networking:FindFirstChild(arg)
				if not sliced22 or not sliced22:IsA("RemoteFunction") then
					return false, nil
				end
				return pcall(sliced22.InvokeServer, sliced22, arg2)
			end

			local function slicedfn37(arg)
				local flag4 = tbl24.MinRarity > 0

				if flag4 then
					local minRarity = tbl24.MinRarity
					flag4 = tbl4.EggRarity(arg) < minRarity
				end

				if flag4 then
					return false
				end
				local flag5 = tbl24.MinIncome > 0

				if flag5 then
					local minIncome = tbl24.MinIncome
					flag5 = tbl4.EggIncome(arg) < minIncome
				end

				if flag5 then
					return false
				end

				if next(tbl24.Eggs) ~= nil and tbl24.Eggs[tostring(arg.AssetCategory)] ~= true then
					return false
				end
				return true
			end

			local function slicedfn38()
				local eggState = tbl.EggState
				if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
					return {}
				end
				local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
				if not ok or type(result) ~= "table" then
					return {}
				end
				local flag4 = tbl4.Toggle(sliced21, false) == true
				local Hatch = tbl4.RiftOn("Hatch") and tbl4.RiftShortfall() or {}
				local tbl25 = {}
				local tbl26 = {}

				for k, sliced22 in pairs(result) do
					local flag5 = type(sliced22) == "table" and sliced22.Placement ~= nil

					if flag5 then
						flag5 = (tbl23[k] or 0) <= os.clock()
					end

					if flag5 then
						local ok2, result2 = pcall(eggState.IsReadyToHatch, k)

						if ok2 and result2 == true then
							local str3 = tostring(sliced22.AssetCategory)

							if (Hatch[str3] or 0) > 0 then
								Hatch[str3] = Hatch[str3] - 1
								table.insert(tbl25, k)
							elseif flag4 and slicedfn37(sliced22) then
								table.insert(tbl26, k)
							end
						end
					end
				end

				for _, sliced22 in ipairs(tbl26) do
					table.insert(tbl25, sliced22)
				end

				return tbl25
			end

			local function slicedfn39()
				return tbl4.Toggle(sliced21, false) or tbl4.RiftOn("Hatch")
			end

			local function slicedfn40()
				local sliced22 = slicedn16
				local sliced23 = slicedfn38()
				local slicedn17 = 0

				for _, sliced24 in ipairs(sliced23) do
					if not (slicedn17 >= slicedn14 or sliced22 ~= slicedn16 or not slicedfn39()) then
						local AskHatch, sliced25 = slicedfn36("RF/EggWorld/AskHatch", sliced24)

						if AskHatch and sliced25 ~= false then
							task.wait(0.35)
							slicedfn36("RF/EggWorld/AskFinishHatch", sliced24)
							slicedn17 += 1
							tbl23[sliced24] = nil
						else
							tbl23[sliced24] = os.clock() + slicedn15
						end

						task.wait(0.2)
						continue
					end

					break
				end

				return slicedn17 > 0
			end

			tbl3.Add(function()
				if not slicedfn39() or flag3 then
					return false
				end
				flag3 = true

				task.spawn(function()
					pcall(slicedfn40)
					flag3 = false
				end)

				return false
			end)

			local function hatch()
				slicedn16 += 1
				table.clear(tbl23)
				tbl3.Wake()
			end

			sliced21 = sliced11:CreateToggle({ Name = "Auto Hatch", Default = false, Callback = hatch })

			sliced11:CreateDropdown({
				Name = "Hatch Min Rarity",
				Note = "Hatch eggs of the chosen rarity and every rarity above it",
				Options = tbl8,
				Default = tbl8[1],
				SubOf = sliced21,
				Callback = function(arg)
					tbl24.MinRarity = tbl9[arg] or 0
					hatch()
				end,
			})

			local tbl25 = {
				["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
				["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
				["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
			}

			local tbl26 = { Slider = nil, Value = 0, Unit = "M/s" }

			local function slicedfn41(arg, arg2)
				if arg ~= nil then
					tbl26.Value = math.max(0, math.floor(tonumber(arg) or tbl26.Value))
				end

				if arg2 ~= nil then
					tbl26.Unit = tostring(arg2)
				end

				tbl24.MinIncome = tbl26.Value * (tbl25[tbl26.Unit] or tbl25["M/s"]).Mult
				hatch()
			end

			tbl26.Slider = slicedfn5(sliced11, {
				Name = "Min Hatch Value",
				Note = "Skip eggs worth less than this (0 = off)",
				SubOf = sliced21,
				Legacy = "Hatch Min Value",
				SectionName = "Auto Hatch & Equip",
				OnRaw = function(arg)
					slicedfn41(math.floor(arg / 1000), "K/s")
				end,
			})

			local tbl27 = {}
			local tbl28 = {}
			local directory = tbl.Assets and tbl.Assets.Directory
			local slicedn17 = 0

			while (type(directory) ~= "table" or next(directory) == nil) and slicedn17 < 2 do
				slicedn17 += task.wait(0.1)

				if type(tbl.Assets) ~= "table" then
					tbl.Assets = slicedfn2(function()
						return ReplicatedStorage.Data.Assets
					end)
				end

				directory = tbl.Assets and tbl.Assets.Directory
			end

			local tbl29 = {}

			if type(directory) == "table" then
				for k, sliced22 in pairs(directory) do
					local rarity = type(sliced22) == "table" and sliced22.Rarity or nil
					local flag4 = type(rarity) == "table"

					if flag4 then
						flag4 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					flag4 = flag4 or nil

					if flag4 then
						table.insert(tbl29, {
							Category = tostring(k),
							Name = tostring(sliced22.DisplayName or k),
							Rarity = flag4,
							RarityName = tostring(rarity.DisplayName or rarity._id or flag4),
						})
					end
				end
			end

			table.sort(tbl29, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity > arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced22 in ipairs(tbl29) do
				local str3 = string.format("%s [%s]", sliced22.Name, sliced22.RarityName)

				if tbl28[str3] then
					str3 = string.format("%s [%s] (%s)", sliced22.Name, sliced22.RarityName, sliced22.Category)
				end

				table.insert(tbl27, str3)
				tbl28[str3] = sliced22.Category
			end

			if #tbl27 > 0 then
				slicedfn6(sliced11:CreateMultiDropdown({
					Name = "Hatch Specific Eggs",
					Note = "Only hatch these eggs (empty = all)",
					Options = tbl27,
					Default = {},
					SubOf = sliced21,
					Callback = function(arg)
						local eggs = {}

						if type(arg) == "table" then
							for k, sliced22 in pairs(arg) do
								k = sliced22 == true and type(k) == "string" and k or type(sliced22) == "string" and sliced22 or nil

								if k and tbl28[k] then
									eggs[tbl28[k]] = true
								end
							end
						end

						tbl24.Eggs = eggs
						hatch()
					end,
				}))
			end

			tbl4.Rift.Restart.Hatch = hatch
		end

		do
			local slicedn14 = 5
			local slicedn15 = 30
			local sliced21 = nil
			local flag3 = false
			local slicedn16 = 0
			local tbl23 = {}
			local slicedn17 = 0
			local flag4 = true
			local sliced22 = nil
			local slicedn18 = -math.huge

			local function slicedfn36(arg)
				local sliced23 = slicedfn2(function()
					return ReplicatedStorage.Data.Bases
				end)

				if type(sliced23) == "table" and type(sliced23.GetAssetEquipCapacity) == "function" then
					local ok, result = pcall(sliced23.GetAssetEquipCapacity, arg and tonumber(arg.BaseUpgradeLevel) or 0)
					if ok and tonumber(result) then
						return math.floor(tonumber(result))
					end
				end

				if sliced22 and os.clock() - slicedn18 < slicedn15 then
					return sliced22
				end
				local rfPenRosterAskWearLimit = networking:FindFirstChild("RF/PenRoster/AskWearLimit")

				if rfPenRosterAskWearLimit and rfPenRosterAskWearLimit:IsA("RemoteFunction") then
					local ok, result = pcall(rfPenRosterAskWearLimit.InvokeServer, rfPenRosterAskWearLimit)

					if ok and tonumber(result) then
						local slicedn19 = math.floor(tonumber(result))
						local now = os.clock()
						sliced22 = slicedn19
						slicedn18 = now
						return sliced22
					end
				end

				local sliced24 = sliced22
				local slicedn19

				if sliced22 then
					slicedn19 = sliced24
				else
					slicedn19 = 0
				end

				return slicedn19
			end

			local function slicedfn37(arg)
				local directory = tbl.Assets and tbl.Assets.Directory
				local flag5 = type(directory) == "table" and directory[tostring(arg.Category)] or nil
				local slicedn19 = type(flag5) == "table" and tonumber(flag5.EarningRate) or 0
				local slicedn20 = tonumber(arg.Scale) or 0
				if slicedn19 <= 0 or slicedn20 <= 0 then
					return 0
				end
				local slicedn21 = slicedn20 > 5 and (slicedn20 / 5) ^ 1.2 * 19.637875755794113 or slicedn20 ^ 1.85
				local mutations = tbl.Mutations
				local flag6 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn22 = 1

				if flag6 then
					local ok, result = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
					ok = ok and type(result) == "number"
					local slicedn23 = 1

					if ok then
						slicedn22 = result
					else
						slicedn22 = slicedn23
					end
				end

				return slicedn19 * slicedn21 * slicedn22
			end

			local function slicedfn38()
				local save3 = tbl.Save
				local result

				if type(save3) == "table" and type(save3.Get) == "function" then
					local ok
					ok, result = pcall(save3.Get)
					result = ok and type(result) == "table" and result or nil
				end

				if not result then
					return nil
				end
				local tbl24 = {}
				local tbl25 = {}
				local pairs = pairs
				local equippedAssets = result.EquippedAssets or {}

				for _, equippedAsset in pairs(equippedAssets) do
					if type(equippedAsset) == "string" then
						tbl24[equippedAsset] = true
						table.insert(tbl25, equippedAsset)
					end
				end

				local tbl26 = {}
				local sliced24 = pairs
				local inventory = result.Inventory or {}

				for k, sliced25 in sliced24(inventory) do
					if type(sliced25) == "table" and sliced25.InFuse ~= true then
						table.insert(tbl26, { Uid = k, Income = slicedfn37(sliced25), Equipped = tbl24[k] == true })
					end
				end

				table.sort(tbl26, function(arg, arg2)
					if arg.Income ~= arg2.Income then
						return arg.Income > arg2.Income
					end
					return tostring(arg.Uid) < tostring(arg2.Uid)
				end)

				return tbl26, tbl24, #tbl25, result
			end

			local function slicedfn39(arg, arg2)
				local tbl24 = {}
				local flag5 = false

				for i, sliced23 in ipairs(arg) do
					if not (arg2 < i) then
						if not sliced23.Equipped then
							table.insert(tbl24, sliced23.Uid)

							if not tbl23[sliced23.Uid] then
								flag5 = true
							end
						end

						continue
					end

					break
				end

				return tbl24, flag5
			end

			tbl3.Add(function()
				if not tbl4.Toggle(sliced21, false) then
					return false
				end
				local sliced23, sliced24, sliced25, sliced26 = slicedfn38()

				if sliced23 then
					local sliced27 = slicedfn36(sliced26)
					local sliced28, sliced29 = slicedfn39(sliced23, sliced27)

					if (sliced29 or flag4) and not flag3 and os.clock() >= slicedn17 then
						for _, sliced30 in ipairs(sliced28) do
							tbl23[sliced30] = true
						end

						flag4 = false
						flag3 = true
						slicedn17 = os.clock() + slicedn14
						local sliced30 = slicedn16

						task.spawn(function()
							local rfHaulFetchWearBestStatus = networking:FindFirstChild("RF/Haul/FetchWearBestStatus")
							local isRemoteFunction = rfHaulFetchWearBestStatus and rfHaulFetchWearBestStatus:IsA("RemoteFunction")
							local flag5 = true

							if isRemoteFunction then
								local ok, result = pcall(rfHaulFetchWearBestStatus.InvokeServer, rfHaulFetchWearBestStatus)
								flag5 = ok and result ~= false and result ~= nil
							end

							local rfHaulWearBest = networking:FindFirstChild("RF/Haul/WearBest")

							if flag5 and sliced30 == slicedn16 and rfHaulWearBest and rfHaulWearBest:IsA("RemoteFunction") then
								pcall(rfHaulWearBest.InvokeServer, rfHaulWearBest)
							end

							flag3 = false
							tbl3.Wake()
						end)
					end
				end

				return false
			end)

			sliced21 = sliced11:CreateToggle({
				Name = "Auto Equip Best",
				Note = "Equip Best when a better pet appears",
				Default = false,
				Callback = function()
					slicedn16 += 1
					table.clear(tbl23)
					slicedn17 = 0
					flag4 = true
					tbl3.Wake()
				end,
			})

			local save3 = tbl.Save

			if type(save3) == "table" and type(save3.FieldSignal) == "function" then
				for _, sliced23 in ipairs({ "Inventory", "EquippedAssets" }) do
					local ok, result = pcall(save3.FieldSignal, sliced23)

					if ok and type(result) == "table" and type(result.Connect) == "function" then
						local ok2, result2 = pcall(result.Connect, result, function()
							flag4 = true
							tbl3.Wake()
						end)

						if ok2 and result2 then
							slicedfn4(function()
								pcall(function()
									result2:Disconnect()
								end)
							end)
						end
					end
				end
			end
		end

		local slicedn14 = 3
		local tbl23, tbl24, tbl25, tbl26, tbl27

		do
			local slicedn15 = 50
			tbl23 = { "Rarity Only", "Value Only", "Rarity And Value", "Rarity Or Value" }

			local sliced21 = slicedfn2(function()
				return ReplicatedStorage.Shared.Util.AssetItems
			end)

			tbl24 = {}
			tbl25 = {}
			tbl26 = {}
			tbl27 = {}
			local directory = tbl.Assets and tbl.Assets.Directory
			local tbl28 = {}
			local tbl29 = {}

			if type(directory) == "table" then
				for k, sliced22 in pairs(directory) do
					local rarity = type(sliced22) == "table" and sliced22.Rarity or nil
					local flag3 = type(rarity) == "table"

					if flag3 then
						flag3 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					flag3 = flag3 or nil

					if flag3 then
						local str3 = tostring(rarity.DisplayName or rarity._id or flag3)
						tbl28[flag3] = tbl28[flag3] or str3

						table.insert(tbl29, {
							Category = tostring(k),
							Name = tostring(sliced22.DisplayName or k),
							Rarity = flag3,
							RarityName = str3,
						})
					end
				end
			end

			local tbl30 = {}

			for k in pairs(tbl28) do
				table.insert(tbl30, k)
			end

			table.sort(tbl30)

			for _, sliced22 in ipairs(tbl30) do
				local str3 = string.format("%d - %s", sliced22, tbl28[sliced22])
				table.insert(tbl24, str3)
				tbl25[str3] = sliced22
			end

			table.sort(tbl29, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity < arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced22 in ipairs(tbl29) do
				local str3 = string.format("%s [%s]", sliced22.Name, sliced22.RarityName)

				if tbl27[str3] then
					str3 = string.format("%s [%s] (%s)", sliced22.Name, sliced22.RarityName, sliced22.Category)
				end

				table.insert(tbl26, str3)
				tbl27[str3] = sliced22.Category
			end

			local function slicedfn36(arg)
				for _, sliced22 in ipairs(tbl24) do
					if tbl25[sliced22] == arg then
						return sliced22
					end
				end

				return tbl24[1]
			end

			local sliced22 = nil
			local sliced23 = nil
			local sliced24 = nil
			local sliced25 = nil
			local sliced26 = tbl23[1]
			local slicedn16 = 3
			local slicedn17 = 0
			local flag3 = true
			local tbl31 = {}
			local sliced27 = tbl23[1]
			local slicedn18 = 3
			local slicedn19 = 0
			local flag4 = true
			local tbl32 = {}
			local flag5 = false
			local slicedn20 = 0

			local function slicedfn37(arg)
				local slicedn21 = tonumber(arg) or 0
				local tbl33 = { "", "K", "M", "B", "T", "Qa", "Qi" }
				local slicedn22 = 1

				while math.abs(slicedn21) >= 1000 and slicedn22 < #tbl33 do
					slicedn21 /= 1000
					slicedn22 += 1
				end

				return string.format(slicedn22 == 1 and "$%.0f%s" or "$%.2f%s", slicedn21, tbl33[slicedn22])
			end

			local function slicedfn38(arg, arg2)
				local tbl33 = {}

				if type(arg) == "table" then
					for k, sliced28 in pairs(arg) do
						k = sliced28 == true and type(k) == "string" and k or type(sliced28) == "string" and sliced28 or nil

						if k then
							tbl33[arg2 and arg2[k] or k] = true
						end
					end
				end

				return tbl33
			end

			local function slicedfn39(arg)
				local directory2 = tbl.Assets and tbl.Assets.Directory
				local flag6 = type(directory2) == "table" and directory2[tostring(arg)] or nil
				local rarity = type(flag6) == "table" and flag6.Rarity or nil
				local flag7 = type(rarity) == "table"

				if flag7 then
					flag7 = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				return flag7 or math.huge
			end

			local function slicedfn40(arg)
				local directory2 = tbl.Assets and tbl.Assets.Directory
				local flag6 = type(directory2) == "table" and directory2[tostring(arg.Category)] or nil
				local slicedn21 = type(flag6) == "table" and tonumber(flag6.EarningRate) or 0
				local slicedn22 = tonumber(arg.Scale) or 0
				if slicedn21 <= 0 or slicedn22 <= 0 then
					return 0
				end
				local slicedn23 = slicedn22 > 5 and (slicedn22 / 5) ^ 1.2 * 19.637875755794113 or slicedn22 ^ 1.85
				local mutations = tbl.Mutations
				local flag7 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn24 = 1

				if flag7 then
					local ok, result = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})

					if ok and type(result) == "number" then
						slicedn24 = result
					end
				end

				return slicedn21 * slicedn23 * slicedn24
			end

			local function slicedfn41(arg)
				return type(arg) == "table" and next(arg) ~= nil
			end

			local function slicedfn42()
				local save3 = tbl.Save
				if type(save3) ~= "table" or type(save3.Get) ~= "function" then
					return nil
				end
				local ok, result = pcall(save3.Get)
				return ok and type(result) == "table" and result or nil
			end

			local function slicedfn43()
				local sliced28 = slicedfn42()
				local tbl33 = {}
				if not sliced28 then
					return tbl33, 0
				end
				local tbl34 = {}
				local pairs = pairs
				local equippedAssets = sliced28.EquippedAssets or {}

				for _, equippedAsset in pairs(equippedAssets) do
					tbl34[equippedAsset] = true
				end

				local sliced30 = pairs
				local inventory = sliced28.Inventory or {}
				local slicedn21 = 0

				for k, sliced31 in sliced30(inventory) do
					local flag6 = type(sliced31) == "table" and sliced31.InFuse ~= true and sliced31.IsFavorite ~= true and not tbl34[k] and not tbl31[tostring(sliced31.Category)]

					if flag6 then
						flag6 = not (flag3 and slicedfn41(sliced31.Mutations))
					end

					if flag6 then
						local sliced32 = slicedfn40(sliced31)
						local flag7 = slicedfn39(sliced31.Category) <= slicedn16
						local flag8 = slicedn17 > 0 and sliced32 < slicedn17

						if sliced26 ~= tbl23[2] then
							if sliced26 == tbl23[3] then
								flag8 = flag7 and flag8
							elseif sliced26 == tbl23[4] then
								flag8 = flag7 or flag8
							else
								flag8 = flag7
							end
						end

						if flag8 then
							table.insert(tbl33, k)
							local flag9 = type(sliced21) == "table" and type(sliced21.SalePrice) == "function"
							local flag10 = false
							local result = nil

							if flag9 then
								flag10, result = pcall(sliced21.SalePrice, sliced31)
							end

							slicedn21 += flag10 and tonumber(result) or sliced32 * 100
						end
					end
				end

				return tbl33, slicedn21
			end

			local function slicedfn44()
				local tbl33 = {}
				local eggState = tbl.EggState
				if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
					return tbl33, 0
				end
				local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
				if not ok or type(result) ~= "table" then
					return tbl33, 0
				end
				local character = localPlayer.Character
				character = character and character:FindFirstChildWhichIsA("Tool")
				character = character and character:GetAttribute("UID") or nil
				local eggRecords = tbl.EggRecords
				local sliced28, sliced29, sliced30 = pairs(result)
				local slicedn21 = 0

				for k, sliced31 in sliced28, sliced29, sliced30 do
					local flag6 = type(sliced31) == "table" and sliced31.Placement == nil and k ~= character and not tbl32[tostring(sliced31.AssetCategory)]

					if flag6 then
						flag6 = not (flag4 and slicedfn41(sliced31.Mutations))
					end

					if flag6 then
						local sliced32 = slicedfn40({ Category = sliced31.AssetCategory, Scale = sliced31.AssetScale, Mutations = sliced31.Mutations })
						local flag7 = slicedfn39(sliced31.AssetCategory) <= slicedn18
						local flag8 = slicedn19 > 0 and sliced32 < slicedn19

						if sliced27 ~= tbl23[2] then
							if sliced27 == tbl23[3] then
								flag8 = flag7 and flag8
							elseif sliced27 ~= tbl23[4] then
								flag8 = flag7
							else
								flag8 = flag7 or flag8
							end
						end

						if flag8 then
							table.insert(tbl33, k)

							if type(eggRecords) == "table" and type(eggRecords.SellPrice) == "function" then
								local ok2, result2 = pcall(eggRecords.SellPrice, sliced31)
								slicedn21 += ok2 and tonumber(result2) or 0
							end
						end
					end
				end

				return tbl33, slicedn21
			end

			local function slicedfn45(arg, arg2)
				local rePetSatchelSellSelection = networking:FindFirstChild("RE/PetSatchel/SellSelection")
				if not rePetSatchelSellSelection or not rePetSatchelSellSelection:IsA("RemoteEvent") then
					return false
				end
				local slicedn21 = math.max(#arg, #arg2)
				local slicedn22 = 1

				while slicedn22 <= slicedn21 do
					local tbl33 = {}
					local tbl34 = {}

					for i = slicedn22, slicedn22 + slicedn15 - 1 do
						if arg[i] then
							table.insert(tbl33, arg[i])
						end

						if arg2[i] then
							table.insert(tbl34, arg2[i])
						end
					end

					pcall(rePetSatchelSellSelection.FireServer, rePetSatchelSellSelection, { Eggs = tbl34, Assets = tbl33 })
					slicedn22 += slicedn15

					if slicedn22 <= slicedn21 then
						task.wait(0.3)
					end
				end

				return true
			end

			local function slicedfn46(arg, arg2)
				local flag6 = flag5

				if not flag5 then
					flag6 = #arg == 0 and #arg2 == 0
				end

				if flag6 then
					return
				end
				flag5 = true
				slicedn20 = os.clock() + slicedn14

				task.spawn(function()
					pcall(slicedfn45, arg, arg2)
					flag5 = false
					tbl3.Wake()
				end)
			end

			tbl3.Add(function()
				local sliced28 = tbl4.Toggle(sliced22, false)
				local sliced29 = tbl4.Toggle(sliced23, false)
				local sliced30, sliced31 = slicedfn43()
				local sliced32, sliced33 = slicedfn44()

				if sliced24 and type(sliced24.Set) == "function" then
					pcall(sliced24.Set, sliced24, string.format("Pet matches  -  %d pets for %s", #sliced30, slicedfn37(sliced31)))
				end

				if sliced25 and type(sliced25.Set) == "function" then
					pcall(sliced25.Set, sliced25, string.format("Egg matches  -  %d eggs for %s", #sliced32, slicedfn37(sliced33)))
				end

				local sliced34 = flag5
				local flag6

				if flag5 then
					flag6 = sliced34
				else
					flag6 = os.clock() < slicedn20
				end

				local flag7

				if flag6 then
					flag7 = flag6
				else
					flag7 = not (sliced28 or sliced29)
				end

				if flag7 then
					return false
				end
				slicedfn46(sliced28 and sliced30 or {}, sliced29 and sliced32 or {})
				return false
			end)

			sliced24 = sliced12:CreateText({ Name = "Pet Sell Preview", Text = "Pet matches  -  0 pets" })

			sliced22 = sliced12:CreateToggle({
				Name = "Auto Sell Pet",
				Default = false,
				Callback = function()
					tbl3.Wake()
				end,
			})

			sliced12:CreateButton({
				Name = "Sell Pets Now",
				ButtonText = "Sell",
				ConfirmText = "Sold!",
				SubOf = sliced22,
				Callback = function()
					slicedfn46(slicedfn43(), {})
				end,
			})

			sliced12:CreateDropdown({
				Name = "Sell Pet Rule",
				Note = "Which checks must pass to sell",
				Options = tbl23,
				Default = tbl23[1],
				SubOf = sliced22,
				Callback = function(arg)
					if table.find(tbl23, arg) then
						sliced26 = arg
						tbl3.Wake()
					end
				end,
			})

			sliced12:CreateDropdown({
				Name = "Pet Max Rarity",
				Note = "Sell pets at or below this rarity",
				Options = tbl24,
				Default = slicedfn36(3),
				SubOf = sliced22,
				Callback = function(arg)
					slicedn16 = tbl25[arg] or slicedn16
					tbl3.Wake()
				end,
			})

			local tbl33 = {
				["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
				["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
				["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
			}

			local function slicedfn47(arg, arg2, arg3, arg4)
				local slicedn21 = 0
				local str3 = "M/s"

				local function slicedfn48(arg5, arg6)
					if arg5 ~= nil then
						slicedn21 = math.max(0, math.floor(tonumber(arg5) or slicedn21))
					end

					if arg6 ~= nil then
						str3 = tostring(arg6)
					end

					arg4(slicedn21 * (tbl33[str3] or tbl33["M/s"]).Mult)
					tbl3.Wake()
				end

				return (slicedfn5(sliced12, {
					Name = arg == "Pet Value Threshold" and "Pet Sell Value" or arg == "Egg Value Threshold" and "Egg Sell Value" or arg,
					Note = arg2,
					SubOf = arg3,
					Legacy = arg,
					SectionName = "Auto Sell",
					OnRaw = function(arg5)
						slicedfn48(math.floor(arg5 / 1000), "K/s")
					end,
				}))
			end

			slicedfn47("Pet Value Threshold", "Sell pets worth less than this (0 = off)", sliced22, function(arg)
				slicedn17 = arg
			end)

			local sliced28 = nil

			sliced28 = sliced12:CreateToggle({
				Name = "Keep Mutated Pets",
				Note = "Never sell mutated pets",
				Default = true,
				SubOf = sliced22,
				Callback = function()
					flag3 = tbl4.Toggle(sliced28, true)
					tbl3.Wake()
				end,
			})

			slicedfn6(sliced12:CreateMultiDropdown({
				Name = "Blacklist Sell Pets",
				Note = "These pets are never sold",
				Options = tbl26,
				Default = {},
				SubOf = sliced22,
				Callback = function(arg)
					tbl31 = slicedfn38(arg, tbl27)
					tbl3.Wake()
				end,
			}))

			sliced25 = sliced12:CreateText({ Name = "Egg Sell Preview", Text = "Egg matches  -  0 eggs" })

			sliced23 = sliced12:CreateToggle({
				Name = "Auto Sell Egg",
				Note = "Sell bag eggs matching the rules below",
				Default = false,
				Callback = function()
					tbl3.Wake()
				end,
			})

			sliced12:CreateButton({
				Name = "Sell Eggs Now",
				Note = "Sell matching eggs once",
				ButtonText = "Sell",
				ConfirmText = "Sold!",
				SubOf = sliced23,
				Callback = function()
					local sliced29 = slicedfn44()
					slicedfn46({}, sliced29)
				end,
			})

			sliced12:CreateDropdown({
				Name = "Sell Egg Rule",
				Note = "Which checks must pass to sell",
				Options = tbl23,
				Default = tbl23[1],
				SubOf = sliced23,
				Callback = function(arg)
					if table.find(tbl23, arg) then
						sliced27 = arg
						tbl3.Wake()
					end
				end,
			})

			sliced12:CreateDropdown({
				Name = "Egg Max Rarity",
				Note = "Sell eggs at or below this rarity",
				Options = tbl24,
				Default = slicedfn36(3),
				SubOf = sliced23,
				Callback = function(arg)
					slicedn18 = tbl25[arg] or slicedn18
					tbl3.Wake()
				end,
			})

			slicedfn47("Egg Value Threshold", "Sell eggs worth less than this (0 = off)", sliced23, function(arg)
				slicedn19 = arg
			end)

			local sliced29 = nil

			sliced29 = sliced12:CreateToggle({
				Name = "Keep Mutated Eggs",
				Note = "Never sell mutated eggs",
				Default = true,
				SubOf = sliced23,
				Callback = function()
					flag4 = tbl4.Toggle(sliced29, true)
					tbl3.Wake()
				end,
			})

			slicedfn6(sliced12:CreateMultiDropdown({
				Name = "Blacklist Sell Eggs",
				Note = "These eggs are never sold",
				Options = tbl26,
				Default = {},
				SubOf = sliced23,
				Callback = function(arg)
					tbl32 = slicedfn38(arg, tbl27)
					tbl3.Wake()
				end,
			}))
		end

		local save3 = tbl.Save

		if type(save3) == "table" and type(save3.FieldSignal) == "function" then
			for _, sliced21 in ipairs({ "Inventory", "EggInventory", "EquippedAssets" }) do
				local ok, result = pcall(save3.FieldSignal, sliced21)

				if ok and type(result) == "table" and type(result.Connect) == "function" then
					local ok2, result2 = pcall(result.Connect, result, function()
						tbl3.Wake()
					end)

					if ok2 and result2 then
						slicedfn4(function()
							pcall(function()
								result2:Disconnect()
							end)
						end)
					end
				end
			end
		end

		local slicedn15 = 2
		local slicedn16 = 3
		local slicedn17 = 20
		local tbl28 = { "Lowest Rarity First", "Highest Rarity First", "Most Copies First", "Lowest Value First" }
		local tbl29 = { "Lowest To Highest", "Highest To Lowest" }
		local tbl30 = {}
		local tbl31 = {}
		local tbl32 = {}
		local tbl33 = {}

		do
			local directory = tbl.Assets and tbl.Assets.Directory
			local tbl34 = {}
			local tbl35 = {}

			if type(directory) == "table" then
				for k, sliced21 in pairs(directory) do
					local rarity = type(sliced21) == "table" and sliced21.Rarity or nil
					local flag3 = type(rarity) == "table"

					if flag3 then
						flag3 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					local sliced22 = flag3 or nil

					if sliced22 then
						local rarityName = tostring(rarity.DisplayName or rarity._id or sliced22)
						tbl34[sliced22] = tbl34[sliced22] or rarityName
						local insert = table.insert
						local tbl36 = { Category = tostring(k) }
						local tostring = tostring
						k = sliced21.DisplayName or k
						tbl36.Name = tostring(k)
						tbl36.Rarity = sliced22
						tbl36.RarityName = rarityName
						insert(tbl35, tbl36)
					end
				end
			end

			local tbl36 = {}

			for k in pairs(tbl34) do
				table.insert(tbl36, k)
			end

			table.sort(tbl36)

			for _, sliced21 in ipairs(tbl36) do
				local str3 = string.format("%d - %s", sliced21, tbl34[sliced21])
				table.insert(tbl30, str3)
				tbl31[str3] = sliced21
			end

			table.sort(tbl35, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity < arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced21 in ipairs(tbl35) do
				local str3 = string.format("%s [%s]", sliced21.Name, sliced21.RarityName)

				if tbl33[str3] then
					str3 = string.format("%s [%s] (%s)", sliced21.Name, sliced21.RarityName, sliced21.Category)
				end

				table.insert(tbl32, str3)
				tbl33[str3] = sliced21.Category
			end
		end

		do
			local function slicedfn36(arg)
				for _, sliced21 in ipairs(tbl30) do
					if tbl31[sliced21] == arg then
						return sliced21
					end
				end

				return tbl30[#tbl30]
			end

			local sliced21 = nil
			local sliced22 = nil
			local sliced23 = tbl28[1]
			local sliced24 = tbl29[1]
			local slicedn18 = 6
			local tbl34 = {}
			local flag3 = true
			local flag4 = true
			local flag5 = false
			local slicedn19 = 0
			local slicedn20 = 0
			local slicedn21 = 0
			local tbl35 = {}

			local function slicedfn37(arg, arg2)
				local sliced25 = networking:FindFirstChild(arg)
				if not sliced25 or not sliced25:IsA("RemoteFunction") then
					return false, nil
				end

				if arg2 == nil then
					return pcall(sliced25.InvokeServer, sliced25)
				end
				return pcall(sliced25.InvokeServer, sliced25, arg2)
			end

			local function slicedfn38()
				local save4 = tbl.Save
				if type(save4) ~= "table" or type(save4.Get) ~= "function" then
					return nil
				end
				local ok, result = pcall(save4.Get)
				return ok and type(result) == "table" and result or nil
			end

			local function slicedfn39(arg)
				local directory = tbl.Assets and tbl.Assets.Directory
				return type(directory) == "table" and directory[tostring(arg)] or nil
			end

			local function slicedfn40(arg)
				local sliced25 = slicedfn39(arg)
				local rarity = type(sliced25) == "table" and sliced25.Rarity or nil
				local flag6 = type(rarity) == "table"

				if flag6 then
					flag6 = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				return flag6 or math.huge
			end

			local function slicedfn41(arg)
				local sliced25 = slicedfn39(arg)
				return tostring(type(sliced25) == "table" and sliced25.DisplayName or arg)
			end

			local function slicedfn42(arg)
				local sliced25 = slicedfn39(arg.Category)
				local slicedn22 = type(sliced25) == "table" and tonumber(sliced25.EarningRate) or 0
				local slicedn23 = tonumber(arg.Scale) or 0
				if slicedn22 <= 0 or slicedn23 <= 0 then
					return 0
				end
				local slicedn24 = slicedn23 > 5 and (slicedn23 / 5) ^ 1.2 * 19.637875755794113 or slicedn23 ^ 1.85
				local mutations = tbl.Mutations
				local flag6 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn25 = 1

				if flag6 then
					local ok
					ok, slicedn25 = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
					local flag7 = ok and type(slicedn25) == "number"
					local slicedn26 = 1

					if not flag7 then
						slicedn25 = slicedn26
					end
				end

				return slicedn22 * slicedn24 * slicedn25
			end

			local function slicedfn43(arg)
				return type(arg) == "table" and next(arg) ~= nil
			end

			local function slicedfn44(arg)
				local slicedn22 = tonumber(arg) or 0
				local tbl36 = { "", "K", "M", "B", "T", "Qa", "Qi" }
				local slicedn23 = 1

				while math.abs(slicedn22) >= 1000 and slicedn23 < #tbl36 do
					slicedn22 /= 1000
					slicedn23 += 1
				end

				return string.format(slicedn23 == 1 and "$%.0f%s" or "$%.2f%s", slicedn22, tbl36[slicedn23])
			end

			local function slicedfn45(arg)
				local fuseKernel = tbl.FuseKernel
				if type(fuseKernel) ~= "table" or type(fuseKernel.PriceFor) ~= "function" then
					return nil
				end
				local ok, result = pcall(fuseKernel.PriceFor, arg)
				return ok and tonumber(result) or nil
			end

			local function slicedfn46(arg, arg2, arg3)
				local flag6 = type(arg2) == "table" and arg2.IsFavorite ~= true and not arg3[arg] and slicedfn40(arg2.Category) <= slicedn18 and (next(tbl34) == nil or tbl34[tostring(arg2.Category)] == true)
				local flag7

				if flag6 then
					flag7 = not (flag3 and slicedfn43(arg2.Mutations))
				else
					flag7 = flag6
				end

				if flag7 then
					flag7 = (tbl35[arg] or 0) <= os.clock()
				end

				return flag7
			end

			local function slicedfn47(arg)
				local inventory = type(arg.Inventory) == "table" and arg.Inventory or {}
				local tbl36 = {}
				local pairs = pairs
				local equippedAssets = arg.EquippedAssets or {}

				for _, equippedAsset in pairs(equippedAssets) do
					tbl36[equippedAsset] = true
				end

				local tbl37 = {}
				local tbl38 = {}

				for i = 1, 3 do
					local flag6 = type(arg.FusionSlots) == "table" and arg.FusionSlots[i] or nil

					if flag6 ~= nil and type(inventory[flag6]) == "table" then
						table.insert(tbl37, flag6)
						tbl38[flag6] = true
					end
				end

				local tbl39 = {}

				for k, sliced26 in pairs(inventory) do
					if not tbl38[k] and type(sliced26) == "table" and sliced26.InFuse ~= true and slicedfn46(k, sliced26, tbl36) then
						local str3 = tostring(sliced26.Category)
						tbl39[str3] = tbl39[str3] or {}
						table.insert(tbl39[str3], { Uid = k, Item = sliced26, Income = slicedfn42(sliced26) })
					end
				end

				local function slicedfn48(arg2)
					table.sort(arg2, function(arg3, arg4)
						if arg3.Income ~= arg4.Income then
							if sliced24 == tbl29[2] then
								return arg3.Income > arg4.Income
							end
							return arg3.Income < arg4.Income
						end

						return tostring(arg3.Uid) < tostring(arg4.Uid)
					end)
				end

				if #tbl37 > 0 then
					local str3 = tostring(inventory[tbl37[1]].Category)
					local flag6 = true

					for _, sliced26 in ipairs(tbl37) do
						local sliced27 = inventory[sliced26]

						if tostring(sliced27.Category) ~= str3 or not slicedfn46(sliced26, sliced27, tbl36) then
							flag6 = false
						end
					end

					local tbl40 = tbl39[str3] or {}

					if flag6 and #tbl37 + #tbl40 >= 3 then
						slicedfn48(tbl40)
						local tbl41 = { Category = str3, Load = {}, Items = {} }

						for _, sliced26 in ipairs(tbl37) do
							table.insert(tbl41.Items, inventory[sliced26])
						end

						for i = 1, 3 - #tbl37 do
							table.insert(tbl41.Load, tbl40[i].Uid)
							table.insert(tbl41.Items, tbl40[i].Item)
						end

						return tbl41
					end

					if flag4 then
						return { Category = str3, Eject = tbl37 }
					end
					return nil, "Machine holds pets that cannot finish a fuse"
				end

				local sliced26 = nil
				local sliced27 = nil

				for k, sliced28 in pairs(tbl39) do
					if #sliced28 >= 3 then
						local sliced29 = slicedfn40(k)
						local slicedn22 = 0

						for _, sliced30 in ipairs(sliced28) do
							slicedn22 += sliced30.Income
						end

						local tbl40

						if sliced23 == tbl28[2] then
							tbl40 = { -sliced29, -#sliced28 }
						elseif sliced23 == tbl28[3] then
							tbl40 = { -#sliced28, sliced29 }
						elseif sliced23 == tbl28[4] then
							tbl40 = { slicedn22 / #sliced28, sliced29 }
						else
							tbl40 = { sliced29, -#sliced28 }
						end

						local flag6 = sliced26 == nil or tbl40[1] < sliced26[1]
						local flag7

						if flag6 then
							flag7 = flag6
						else
							local flag8 = tbl40[1] == sliced26[1]

							if flag8 then
								local flag9 = tbl40[2] < sliced26[2]

								if flag9 then
									flag7 = flag9
								else
									flag7 = tbl40[2] == sliced26[2] and k < sliced27
								end
							else
								flag7 = flag8
							end
						end

						if flag7 then
							sliced26 = tbl40
							sliced27 = k
						end
					end
				end

				if not sliced27 then
					return nil, "No three matching pets"
				end
				local sliced28 = tbl39[sliced27]
				slicedfn48(sliced28)
				local tbl40 = { Category = sliced27, Load = {}, Items = {} }

				for i = 1, 3 do
					table.insert(tbl40.Load, sliced28[i].Uid)
					table.insert(tbl40.Items, sliced28[i].Item)
				end

				return tbl40
			end

			local function slicedfn48(arg)
				local sliced25 = slicedfn38()
				if not sliced25 then
					return
				end

				if sliced25.FusionLocked == true then
					if type(sliced25.FusionEggReward) == "table" and os.clock() >= slicedn21 then
						slicedn21 = os.clock() + slicedn16
						slicedfn37("RF/Fusery/FinishReveal")
					end

					return
				end

				local sliced26 = slicedfn47(sliced25)
				if not sliced26 then
					return
				end

				if sliced26.Eject then
					for _, sliced27 in ipairs(sliced26.Eject) do
						if arg ~= slicedn19 then
							return
						end
						slicedfn37("RF/Fusery/EjectPet", sliced27)
						task.wait(0.35)
					end

					return
				end

				local sliced27 = slicedfn45(sliced26.Items)
				local num = tonumber(sliced25.Money)
				if sliced27 and num and num < sliced27 then
					return
				end

				for _, sliced28 in ipairs(sliced26.Load) do
					if arg ~= slicedn19 then
						return
					end
					local LoadPet, sliced29 = slicedfn37("RF/Fusery/LoadPet", sliced28)
					if not LoadPet or sliced29 == false then
						tbl35[sliced28] = os.clock() + slicedn17
						return
					end
					task.wait(0.35)
				end

				if arg ~= slicedn19 then
					return
				end
				local BeginFuse, sliced28 = slicedfn37("RF/Fusery/BeginFuse")

				if BeginFuse and sliced28 ~= false then
					slicedn21 = os.clock() + slicedn16
				end
			end

			local function slicedfn49(arg)
				if not arg then
					return "Fuse status unknown"
				end

				if arg.FusionLocked == true then
					return "Machine is fusing, waiting for the egg"
				end
				local sliced25, sliced26 = slicedfn47(arg)
				if not sliced25 then
					return sliced26 or "No three matching pets"
				end

				if sliced25.Eject then
					return string.format("Would eject %d %s that cannot finish a fuse", #sliced25.Eject, slicedfn41(sliced25.Category))
				end
				local sliced27 = slicedfn45(sliced25.Items)
				local num = tonumber(arg.Money)
				local str3 = sliced27 and num and num < sliced27 and "  (not enough money)" or ""
				return string.format("Next fuse  -  3 %s for %s%s", slicedfn41(sliced25.Category), sliced27 and slicedfn44(sliced27) or "?", str3)
			end

			tbl3.Add(function()
				local sliced25 = slicedfn38()

				if sliced22 and type(sliced22.Set) == "function" then
					pcall(sliced22.Set, sliced22, slicedfn49(sliced25))
				end

				if not tbl4.Toggle(sliced21, false) or flag5 or os.clock() < slicedn20 then
					return false
				end
				flag5 = true
				slicedn20 = os.clock() + slicedn15
				local sliced26 = slicedn19

				task.spawn(function()
					pcall(slicedfn48, sliced26)
					flag5 = false
					tbl3.Wake()
				end)

				return false
			end)

			sliced22 = sliced13:CreateText({ Name = "Fuse Preview", Text = "Fuse status unknown" })

			sliced21 = sliced13:CreateToggle({
				Name = "Auto Fuse Machine",
				Note = "Fuse 3 same pets into an egg, nonstop",
				Default = false,
				Callback = function()
					slicedn19 += 1
					table.clear(tbl35)
					slicedn20 = 0
					tbl3.Wake()
				end,
			})

			sliced13:CreateDropdown({
				Name = "Fuse Priority Mode",
				Options = tbl28,
				Default = tbl28[1],
				SubOf = sliced21,
				Callback = function(arg)
					if table.find(tbl28, arg) then
						sliced23 = arg
						tbl3.Wake()
					end
				end,
			})

			sliced13:CreateDropdown({
				Name = "Pets To Use",
				Options = tbl29,
				Default = tbl29[1],
				SubOf = sliced21,
				Callback = function(arg)
					if table.find(tbl29, arg) then
						sliced24 = arg
						tbl3.Wake()
					end
				end,
			})

			sliced13:CreateDropdown({
				Name = "Max Rarity to Fuse",
				Options = tbl30,
				Default = slicedfn36(6),
				SubOf = sliced21,
				Callback = function(arg)
					slicedn18 = tbl31[arg] or slicedn18
					tbl3.Wake()
				end,
			})

			slicedfn6(sliced13:CreateMultiDropdown({
				Name = "Specific Species to Fuse",
				Note = "Only fuse these species (empty = all)",
				Options = tbl32,
				Default = {},
				SubOf = sliced21,
				Callback = function(arg)
					local tbl36 = {}

					if type(arg) == "table" then
						for k, sliced25 in pairs(arg) do
							k = sliced25 == true and type(k) == "string" and k

							if k then
								sliced25 = k
							else
								sliced25 = type(sliced25) == "string" and sliced25
							end

							sliced25 = sliced25 or nil

							if sliced25 and tbl33[sliced25] then
								tbl36[tbl33[sliced25]] = true
							end
						end
					end

					tbl34 = tbl36
					tbl3.Wake()
				end,
			}))

			local sliced25 = nil

			sliced25 = sliced13:CreateToggle({
				Name = "Skip Mutated Pets",
				Default = true,
				SubOf = sliced21,
				Callback = function()
					flag3 = tbl4.Toggle(sliced25, true)
					tbl3.Wake()
				end,
			})

			local sliced26 = nil

			sliced26 = sliced13:CreateToggle({
				Name = "Eject Incomplete Slots",
				Note = "Take out pets that can't make a set",
				Default = true,
				SubOf = sliced21,
				Callback = function()
					flag4 = tbl4.Toggle(sliced26, true)
					tbl3.Wake()
				end,
			})
		end

		local save4 = tbl.Save

		if type(save4) == "table" and type(save4.FieldSignal) == "function" then
			for _, sliced21 in ipairs({
				"Inventory",
				"EquippedAssets",
				"FusionSlots",
				"FusionLocked",
				"FusionEggReward",
				"Money",
			}) do
				local ok, result = pcall(save4.FieldSignal, sliced21)

				if ok and type(result) == "table" and type(result.Connect) == "function" then
					local ok2, result2 = pcall(result.Connect, result, function()
						tbl3.Wake()
					end)

					if ok2 and result2 then
						slicedfn4(function()
							pcall(function()
								result2:Disconnect()
							end)
						end)
					end
				end
			end
		end
	end

	do
		local n = 2
		local slicedn2 = 25
		local slicedn3 = 4
		local tbl10 = { "Match Any", "Match All" }
		local tbl11 = { "Golden", "Silver", "Rainbow", "Boss", "Monstrous", "Sakura", "GreatBloom" }
		local str = "Any Mutation"
		local tbl12 = { "Off" }
		local tbl13 = {}
		local tbl14 = {}
		local tbl15 = {}
		local tbl16 = { "Any Mutation" }
		local tbl17 = {}
		local directory = tbl.Assets and tbl.Assets.Directory
		local tbl18 = {}
		local tbl19 = {}

		if type(directory) == "table" then
			for k, sliced8 in pairs(directory) do
				local rarity = type(sliced8) == "table" and sliced8.Rarity or nil
				local flag = type(rarity) == "table"

				if flag then
					flag = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				local sliced9 = flag or nil

				if sliced9 then
					local rarityName = tostring(rarity.DisplayName or rarity._id or sliced9)
					tbl18[sliced9] = tbl18[sliced9] or rarityName
					local insert = table.insert
					local tbl20 = { Category = tostring(k) }
					local tostring = tostring
					k = sliced8.DisplayName or k
					tbl20.Name = tostring(k)
					tbl20.Rarity = sliced9
					tbl20.RarityName = rarityName
					insert(tbl19, tbl20)
				end
			end
		end

		local tbl20 = {}

		for k in pairs(tbl18) do
			table.insert(tbl20, k)
		end

		table.sort(tbl20)

		for _, sliced8 in ipairs(tbl20) do
			local str2 = string.format("%d - %s", sliced8, tbl18[sliced8])
			table.insert(tbl12, str2)
			tbl13[str2] = sliced8
		end

		table.sort(tbl19, function(arg, arg2)
			if arg.Rarity ~= arg2.Rarity then
				return arg.Rarity < arg2.Rarity
			end
			return arg.Name < arg2.Name
		end)

		for _, sliced8 in ipairs(tbl19) do
			local str2 = string.format("%s [%s]", sliced8.Name, sliced8.RarityName)

			if tbl15[str2] then
				str2 = string.format("%s [%s] (%s)", sliced8.Name, sliced8.RarityName, sliced8.Category)
			end

			table.insert(tbl14, str2)
			tbl15[str2] = sliced8.Category
		end

		local tbl21 = {}
		local mutations = tbl.Mutations

		if type(mutations) == "table" and type(mutations.IdSet) == "table" then
			for k in pairs(mutations.IdSet) do
				table.insert(tbl21, tostring(k))
			end
		end

		if #tbl21 == 0 then
			tbl21 = table.clone(tbl11)
		end

		table.sort(tbl21, function(arg, arg2)
			return slicedfn7(arg) < slicedfn7(arg2)
		end)

		for _, sliced8 in ipairs(tbl21) do
			local sliced9 = slicedfn7(sliced8)
			table.insert(tbl16, sliced9)
			tbl17[sliced9] = sliced8
		end

		local sliced8 = nil
		local sliced9 = nil
		local sliced10 = nil
		local sliced11 = nil
		local sliced12 = tbl10[2]
		local sliced13 = nil
		local flag = false
		local tbl22 = {}
		local slicedn4 = 0
		local tbl23 = {}
		local flag2 = false
		local slicedn5 = 0
		local tbl24 = {}

		local function slicedfn8()
			local save = tbl.Save
			if type(save) ~= "table" or type(save.Get) ~= "function" then
				return nil
			end
			local ok, result = pcall(save.Get)
			return ok and type(result) == "table" and result or nil
		end

		local function slicedfn9(arg)
			local directory2 = tbl.Assets and tbl.Assets.Directory
			return type(directory2) == "table" and directory2[tostring(arg)] or nil
		end

		local function slicedfn10(arg)
			local sliced14 = slicedfn9(arg)
			local rarity = type(sliced14) == "table" and sliced14.Rarity or nil
			local flag3 = type(rarity) == "table"

			if flag3 then
				flag3 = tonumber(rarity.RarityNumber or rarity.Rank)
			end

			return flag3 or 0
		end

		local function slicedfn11(arg)
			local sliced14 = slicedfn9(arg.Category)
			local slicedn6 = type(sliced14) == "table" and tonumber(sliced14.EarningRate) or 0
			local slicedn7 = tonumber(arg.Scale) or 0
			if slicedn6 <= 0 or slicedn7 <= 0 then
				return 0
			end
			local slicedn8 = slicedn7 > 5 and (slicedn7 / 5) ^ 1.2 * 19.637875755794113 or slicedn7 ^ 1.85
			local mutations2 = tbl.Mutations
			local flag3 = type(mutations2) == "table" and type(mutations2.EarningsFor) == "function"
			local slicedn9 = 1

			if flag3 then
				local ok
				ok, slicedn9 = pcall(mutations2.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
				ok = ok and type(slicedn9) == "number"
				local slicedn10 = 1

				if not ok then
					slicedn9 = slicedn10
				end
			end

			return slicedn6 * slicedn8 * slicedn9
		end

		local function slicedfn12(arg)
			local tbl25 = {}

			if type(arg.Mutations) == "table" then
				for k, mutation in pairs(arg.Mutations) do
					if type(mutation) == "string" then
						tbl25[mutation] = true
					elseif mutation == true and type(k) == "string" then
						tbl25[k] = true
					end
				end
			end

			if type(arg.BaseMutation) == "string" and arg.BaseMutation ~= "" then
				tbl25[arg.BaseMutation] = true
			end

			return tbl25
		end

		local function slicedfn13(arg)
			if tbl23[tostring(arg.Category)] then
				return true
			end
			local slicedn6 = 0
			local slicedn7 = 0

			if sliced13 then
				slicedn7 = 1

				if slicedfn10(arg.Category) >= sliced13 then
					slicedn6 = 1
				end
			end

			if flag or next(tbl22) ~= nil then
				slicedn7 += 1
				local sliced14 = slicedfn12(arg)

				if flag and next(sliced14) ~= nil then
					slicedn6 += 1
				else
					local flag3 = false

					for k in pairs(sliced14) do
						if tbl22[k] then
							flag3 = true
							break
						end
					end

					if flag3 then
						slicedn6 += 1
					end
				end
			end

			if slicedn4 > 0 then
				slicedn7 += 1

				if slicedn4 <= slicedfn11(arg) then
					slicedn6 += 1
				end
			end

			if slicedn7 == 0 then
				return false
			end

			if sliced12 == tbl10[2] then
				return slicedn6 == slicedn7
			end
			return slicedn6 > 0
		end

		local function slicedfn14(arg)
			return (tbl24[arg] or 0) > os.clock()
		end

		local function slicedfn15(arg)
			local tbl25 = {}
			local sliced14, sliced15, sliced16 = pairs(arg.Inventory or {})
			local slicedn6 = 0

			for k, sliced17 in sliced14, sliced15, sliced16 do
				if type(sliced17) == "table" and slicedfn13(sliced17) then
					slicedn6 += 1

					if sliced17.IsFavorite ~= true and not slicedfn14(k) then
						table.insert(tbl25, k)
					end
				end
			end

			return tbl25, slicedn6
		end

		local function slicedfn16(arg, arg2, arg3)
			local tbl25 = {}
			local inventory = arg.Inventory or {}
			local pairs = pairs
			local equippedAssets = arg.EquippedAssets or {}

			for _, equippedAsset in pairs(equippedAssets) do
				local sliced15 = inventory[equippedAsset]

				if type(sliced15) == "table" and not slicedfn14(equippedAsset) then
					if arg2 then
						if sliced15.IsFavorite ~= true then
							table.insert(tbl25, equippedAsset)
						end
					else
						local flag3 = sliced15.IsFavorite == true

						if flag3 then
							flag3 = not (arg3 and slicedfn13(sliced15))
						end

						if flag3 then
							table.insert(tbl25, equippedAsset)
						end
					end
				end
			end

			return tbl25
		end

		local function slicedfn17(arg, arg2)
			local rePetSatchelWriteFavourite = networking:FindFirstChild("RE/PetSatchel/WriteFavourite")
			if not rePetSatchelWriteFavourite or not rePetSatchelWriteFavourite:IsA("RemoteEvent") then
				return
			end

			for i, sliced14 in ipairs(arg) do
				if not (slicedn2 < i) then
					tbl24[sliced14] = os.clock() + slicedn3
					pcall(rePetSatchelWriteFavourite.FireServer, rePetSatchelWriteFavourite, sliced14, arg2)
					task.wait(0.12)
					continue
				end

				break
			end
		end

		local function slicedfn18(arg, arg2)
			if flag2 or #arg == 0 then
				return false
			end
			flag2 = true
			slicedn5 = os.clock() + n

			task.spawn(function()
				pcall(slicedfn17, arg, arg2)
				flag2 = false
				tbl3.Wake()
			end)

			return true
		end

		tbl3.Add(function()
			local sliced14 = slicedfn8()
			if not sliced14 then
				return false
			end
			local sliced15 = tbl4.Toggle(sliced8, false)
			local sliced16, sliced17 = slicedfn15(sliced14)

			if sliced11 and type(sliced11.Set) == "function" then
				local pairs = pairs
				local inventory = sliced14.Inventory or {}
				local slicedn6 = 0

				for _, sliced19 in pairs(inventory) do
					if type(sliced19) == "table" and sliced19.IsFavorite == true then
						slicedn6 += 1
					end
				end

				pcall(sliced11.Set, sliced11, string.format("Favorite matches  -  %d pets, %d to mark  |  %d favorited", sliced17, #sliced16, slicedn6))
			end

			local sliced18 = flag2
			local flag3

			if flag2 then
				flag3 = sliced18
			else
				flag3 = os.clock() < slicedn5
			end

			if flag3 then
				return false
			end

			if sliced15 and slicedfn18(sliced16, true) then
				return false
			end

			if tbl4.Toggle(sliced9, false) then
				if slicedfn18(slicedfn16(sliced14, true, false), true) then
					return false
				end
			elseif tbl4.Toggle(sliced10, false) then
				slicedfn18(slicedfn16(sliced14, false, sliced15), false)
			end

			return false
		end)

		sliced11 = sliced7:CreateText({ Name = "Favorite Preview", Text = "Favorite matches  -  0 pets" })

		sliced8 = sliced7:CreateToggle({
			Name = "Auto Favorite Pet",
			Note = "Favorite pets matching the rules below",
			Default = false,
			Callback = function()
				table.clear(tbl24)
				tbl3.Wake()
			end,
		})

		sliced7:CreateButton({
			Name = "Favorite Pets Now",
			Note = "Favorite matching pets once",
			ButtonText = "Favorite",
			ConfirmText = "Done!",
			SubOf = sliced8,
			Callback = function()
				local sliced14 = slicedfn8()

				if sliced14 then
					slicedfn18(slicedfn15(sliced14), true)
				end
			end,
		})

		sliced7:CreateDropdown({
			Name = "Favorite Rule",
			Note = "Pass any check or all checks",
			Options = tbl10,
			Default = tbl10[2],
			SubOf = sliced8,
			Callback = function(arg)
				if table.find(tbl10, arg) then
					sliced12 = arg
					tbl3.Wake()
				end
			end,
		})

		sliced7:CreateDropdown({
			Name = "Favorite Min Rarity",
			Note = "Favorite pets of the chosen rarity and every rarity above it (Off = skip)",
			Options = tbl12,
			Default = "Off",
			SubOf = sliced8,
			Callback = function(arg)
				sliced13 = tbl13[arg]
				tbl3.Wake()
			end,
		})

		slicedfn6(sliced7:CreateMultiDropdown({
			Name = "Favorite Mutations",
			Note = "Mutation check (empty = skip)",
			Options = tbl16,
			Default = {},
			SubOf = sliced8,
			Callback = function(arg)
				local tbl25 = {}
				local flag3 = false

				if type(arg) == "table" then
					for k, sliced14 in pairs(arg) do
						k = sliced14 == true and type(k) == "string" and k

						if k then
							sliced14 = k
						else
							sliced14 = type(sliced14) == "string" and sliced14
						end

						local sliced15 = sliced14 or nil

						if sliced15 == str then
							flag3 = true
						elseif sliced15 then
							tbl25[tbl17[sliced15] or sliced15] = true
						end
					end
				end

				flag = flag3
				tbl22 = tbl25
				tbl3.Wake()
			end,
		}))

		local tbl25 = {
			["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
			["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
			["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
		}

		local slicedn6 = 0
		local str2 = "M/s"

		local function slicedfn19(arg, arg2)
			if arg ~= nil then
				slicedn6 = math.max(0, math.floor(tonumber(arg) or slicedn6))
			end

			if arg2 ~= nil then
				str2 = tostring(arg2)
			end

			slicedn4 = slicedn6 * (tbl25[str2] or tbl25["M/s"]).Mult
			tbl3.Wake()
		end

		slicedfn5(sliced7, {
			Name = "Min Favorite Value",
			Note = "Value check (0 = skip)",
			SubOf = sliced8,
			Legacy = "Favorite Min Value",
			SectionName = "Auto Favorite",
			OnRaw = function(arg)
				slicedfn19(math.floor(arg / 1000), "K/s")
			end,
		})

		slicedfn6(sliced7:CreateMultiDropdown({
			Name = "Always Favorite Species",
			Note = "Always favorite these species",
			Options = tbl14,
			Default = {},
			SubOf = sliced8,
			Callback = function(arg)
				local tbl26 = {}

				if type(arg) == "table" then
					for k, sliced14 in pairs(arg) do
						k = sliced14 == true and type(k) == "string" and k or type(sliced14) == "string" and sliced14
						local sliced15 = k or nil

						if sliced15 and tbl15[sliced15] then
							tbl26[tbl15[sliced15]] = true
						end
					end
				end

				tbl23 = tbl26
				tbl3.Wake()
			end,
		}))

		sliced9 = sliced7:CreateToggle({
			Name = "Auto Favorite Equipped",
			Note = "Keep equipped pets favorited",
			Default = false,
			Callback = function()
				tbl3.Wake()
			end,
		})

		sliced10 = sliced7:CreateToggle({
			Name = "Auto Unfavorite Equipped",
			Note = "Unfavorite equipped pets not in the rules",
			Default = false,
			Callback = function()
				tbl3.Wake()
			end,
		})

		sliced7:CreateButton({
			Name = "Favorite Equipped Now",
			Note = "Favorite all equipped pets once",
			ButtonText = "Favorite",
			ConfirmText = "Done!",
			Callback = function()
				local sliced14 = slicedfn8()

				if sliced14 then
					slicedfn18(slicedfn16(sliced14, true, false), true)
				end
			end,
		})

		sliced7:CreateButton({
			Name = "Unfavorite Equipped Now",
			Note = "Unfavorite all equipped pets once",
			ButtonText = "Unfavorite",
			ConfirmText = "Done!",
			Callback = function()
				local sliced14 = slicedfn8()

				if sliced14 then
					slicedfn18(slicedfn16(sliced14, false, false), false)
				end
			end,
		})
	end

	local save = tbl.Save

	if type(save) == "table" and type(save.FieldSignal) == "function" then
		for _, sliced8 in ipairs({ "Inventory", "EquippedAssets" }) do
			local ok, result = pcall(save.FieldSignal, sliced8)

			if ok and type(result) == "table" and type(result.Connect) == "function" then
				local ok2, result2 = pcall(result.Connect, result, function()
					tbl3.Wake()
				end)

				if ok2 and result2 then
					slicedfn4(function()
						pcall(function()
							result2:Disconnect()
						end)
					end)
				end
			end
		end
	end

	tbl4.MechBoot = function(arg)
		local ok, result = pcall(function()
			return require(ReplicatedStorage.Shared.Util.ScrambleBossHazards)
		end)

		local mech = {
			Handle = nil,
			Row = nil,
			Status = "Idle",
			Shown = nil,
			Busy = false,
			Generation = 0,
			Hazards = {},
			TravelSpeed = 250,
			Radius = 18,
			SwingGap = 0.12,
			Dodge = true,
			TryBall = true,
			Leave = true,
			BaitSpeed = 225,
			Interval = 1800,
			Run = nil,
			SwapTools = true,
			SwapIndex = 1,
			SwapSince = 0,
			MainHold = 0.3,
			SecondHold = 0.4,
			LastSwing = 0,
			Links = {},
		}

		tbl4.Mech = mech

		local function slicedfn8()
			return tbl4.Toggle(mech.Handle, false) == true
		end

		local function slicedfn9()
			return workspace:FindFirstChild("ScrambleArena")
		end

		local function slicedfn10()
			return workspace:FindFirstChild("ScrambleArenaPortal")
		end

		local function slicedfn11()
			return localPlayer:GetAttribute("InScrambleArena") == true
		end

		mech.StealFirst = function()
			local steal = tbl4.Steal
			local movement = tbl4.Movement
			if movement.PlaceWanted == true then
				return "Auto Place Egg goes first"
			end

			if movement.MutationWanted == true then
				return "Scrambled Mutation goes first"
			end
			local flag = tbl4.Toggle(sliced5, false) == true and steal ~= nil
			local flag2

			if flag then
				flag2 = steal.Wanted == true or steal.Carrying == true or steal.Active == true
			else
				flag2 = flag
			end

			if flag2 then
				return "Auto Steal goes first"
			end
			return nil
		end

		pcall(function()
			local scheduleIntervalSeconds = require(ReplicatedStorage.Shared.Flags.ScrambleBossFlags).ScheduleIntervalSeconds
			local interval = type(scheduleIntervalSeconds) == "table" and tonumber(scheduleIntervalSeconds.Value) or nil

			if interval and interval > 0 then
				mech.Interval = interval
			end
		end)

		mech.Clock = function(arg2)
			local n = math.max(0, math.floor(arg2 + 0.5))
			return string.format("%d:%02d", math.floor(n / 60), n % 60)
		end

		mech.Timer = function()
			local serverTimeNow = workspace:GetServerTimeNow()
			local scrambleArena = workspace:FindFirstChild("ScrambleArena")
			local n = scrambleArena and tonumber(scrambleArena:GetAttribute("SpawnsAt")) or 0

			if workspace:FindFirstChild("ScrambleArenaPortal") then
				if serverTimeNow < n then
					return "Mech portal is open  |  boss spawns in " .. mech.Clock(n - serverTimeNow)
				end
				return "Mech portal is open now"
			end

			local interval = mech.Interval
			return "Next Mech portal in " .. mech.Clock(math.ceil(serverTimeNow / interval) * interval - serverTimeNow)
		end

		local function slicedfn12(arg2)
			if not arg2 then
				return nil
			end
			local hitbox = arg2:FindFirstChild("Hitbox", true)
			if hitbox and hitbox:IsA("BasePart") then
				return hitbox
			end

			for _, descendant in ipairs(arg2:GetDescendants()) do
				if descendant:IsA("TouchTransmitter") and descendant.Parent and descendant.Parent:IsA("BasePart") then
					return descendant.Parent
				end
			end

			return nil
		end

		local function slicedfn13(arg2)
			local sliced8 = tbl4.Root()
			if not sliced8 or not arg2 or type(firetouchinterest) ~= "function" then
				return
			end

			pcall(function()
				firetouchinterest(sliced8, arg2, 0)
				task.wait(0.05)
				firetouchinterest(sliced8, arg2, 1)
			end)
		end

		local function slicedfn14(arg2, arg3)
			if not mech.Dodge or not ok or type(result) ~= "table" or type(result.Contains) ~= "function" then
				return false
			end

			for k, hazard in pairs(mech.Hazards) do
				local n = tonumber(hazard.At) or 0
				local slicedn2 = tonumber(hazard.Warn) or 0
				if arg3 > n + (tonumber(hazard.Duration) or 0.5) + 1.5 then
					mech.Hazards[k] = nil
					continue
				end

				if arg3 >= n - slicedn2 - 0.1 then
					local ok2, result2 = pcall(result.Contains, hazard, arg2, arg3)
					if ok2 and result2 then
						return true
					end
				end
			end

			return false
		end

		local function slicedfn15()
			local character = localPlayer.Character
			local backpack = localPlayer:FindFirstChildOfClass("Backpack")

			for _, sliced8 in ipairs({ character, backpack }) do
				if sliced8 then
					for _, child in ipairs(sliced8:GetChildren()) do
						if child:IsA("Tool") and tostring(child:GetAttribute("ItemType")) == "Gear" then
							if string.find(string.lower(tostring(child:GetAttribute("GearName") or "")), "scrambler", 1, true) then
								return child
							end
						end
					end
				end
			end

			return nil
		end

		local function slicedfn16()
			local lastSwing = mech.LastSwing
			if os.clock() - lastSwing < mech.SwingGap then
				return
			end
			mech.LastSwing = os.clock()
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")
			local flag = type(tbl4.FindBat) == "function" and tbl4.FindBat() or nil
			local swapTools = mech.SwapTools and slicedfn15() or nil
			local flag2

			if flag and swapTools and flag ~= swapTools then
				local secondHold = mech.SwapIndex == 2 and mech.SecondHold or mech.MainHold
				local swapSince = mech.SwapSince

				if secondHold <= os.clock() - swapSince then
					mech.SwapIndex = mech.SwapIndex == 2 and 1 or 2
					mech.SwapSince = os.clock()
				end

				flag2 = mech.SwapIndex == 2 and swapTools or flag
			else
				flag2 = flag or swapTools
			end

			if not flag2 or not humanoid then
				return
			end

			if flag2.Parent ~= character then
				pcall(function()
					humanoid:EquipTool(flag2)
				end)
			end

			pcall(function()
				flag2:Activate()
			end)
		end

		local function slicedfn17(arg2, arg3)
			local character = localPlayer.Character
			local sliced8 = tbl4.Root()
			if not character or not sliced8 then
				return
			end

			if (sliced8.Position - arg2).Magnitude > 3 then
				pcall(function()
					character:PivotTo(CFrame.lookAt(arg2, Vector3.new(arg3.X, arg2.Y, arg3.Z)))
					sliced8.AssemblyLinearVelocity = Vector3.zero
				end)
			end
		end

		local function slicedfn18(arg2)
			local mech2 = arg2:FindFirstChild("Mech")
			local hitbox = mech2 and mech2:FindFirstChild("Hitbox")
			if hitbox and hitbox:IsA("BasePart") then
				return hitbox.Position, mech2
			end

			for _, child in ipairs(arg2:GetChildren()) do
				if child:IsA("Model") and child.Name ~= "Ball" and child.Name ~= "LeaveTeleport" and child.Name ~= "Structure" then
					local hitbox2 = child:FindFirstChild("Hitbox")
					if hitbox2 and hitbox2:IsA("BasePart") then
						return hitbox2.Position, child
					end
				end
			end

			return nil, nil
		end

		local function slicedfn19(arg2, arg3)
			local ball = arg2:FindFirstChild("Ball")
			if not ball then
				return false
			end
			local position = ball:GetBoundingBox().Position
			local n = (tonumber(arg2:GetAttribute("FloorY")) or position.Y) + 3
			local slicedn2 = tonumber(arg2:GetAttribute("CoreStage")) or 0

			if arg2:GetAttribute("BallStunned") == true then
				mech.Run = nil
				local vector = Vector3.new(arg3.Position.X - position.X, 0, arg3.Position.Z - position.Z)
				local unit = vector.Magnitude > 1 and vector.Unit or Vector3.new(1, 0, 0)
				slicedfn17(Vector3.new(position.X, n, position.Z) + unit * 10, position)
				slicedfn16()
				mech.Status = string.format("Smashing the core  |  stage %d / 3  |  core %s", slicedn2, tostring(arg2:GetAttribute("CoreHealth") or "?"))
				return true
			end

			local str = tostring(arg2:GetAttribute("BallTarget"))
			local attribute = arg2:GetAttribute("BallCoil")

			if not mech.Run and str == tostring(localPlayer.UserId) and type(attribute) == "string" and attribute ~= "" then
				local coils = arg2:FindFirstChild("Coils")
				coils = coils and coils:FindFirstChild(attribute)
				coils = coils and coils:GetAttribute("Home")

				if typeof(coils) == "Vector3" then
					local vector = Vector3.new(coils.X - position.X, 0, coils.Z - position.Z)

					if vector.Magnitude > 1 then
						local slicedn3 = vector.Unit * 40
						mech.Run = { Goal = Vector3.new(coils.X, n, coils.Z) + slicedn3, Until = os.clock() + 8, Coil = attribute }
					end
				end
			end

			if mech.Run then
				local vector = Vector3.new(mech.Run.Goal.X - arg3.Position.X, 0, mech.Run.Goal.Z - arg3.Position.Z)
				local flag = vector.Magnitude < 4

				if not flag then
					local until_ = mech.Run.Until
					flag = os.clock() > until_
				end

				if flag then
					mech.Run = nil

					pcall(function()
						arg3.AssemblyLinearVelocity = Vector3.new(0, arg3.AssemblyLinearVelocity.Y, 0)
					end)
				else
					local slicedn3 = vector.Unit * mech.BaitSpeed

					pcall(function()
						arg3.AssemblyLinearVelocity = Vector3.new(slicedn3.X, arg3.AssemblyLinearVelocity.Y, slicedn3.Z)
					end)

					mech.Status = string.format("Baiting the ball into %s  |  stage %d / 3", mech.Run.Coil, slicedn2)
				end

				return true
			end

			local vector = Vector3.new(arg3.Position.X - position.X, 0, arg3.Position.Z - position.Z)

			if vector.Magnitude > 18 or vector.Magnitude < 6 then
				local vector2 = vector.Magnitude < 1 and Vector3.new(1, 0, 0) or vector.Unit
				slicedfn17(Vector3.new(position.X, n, position.Z) + vector2 * 12, position)
			end

			mech.Status = string.format("Ball phase, waiting for it to lock on  |  stage %d / 3", slicedn2)
			return true
		end

		local function slicedfn20(arg2, arg3)
			local scrambleHuman = arg2:FindFirstChild("ScrambleHuman")
			if not scrambleHuman then
				return false
			end
			local humanoidRootPart = scrambleHuman:FindFirstChild("HumanoidRootPart") or scrambleHuman.PrimaryPart or scrambleHuman:FindFirstChildWhichIsA("BasePart")
			local position = humanoidRootPart and humanoidRootPart.Position or scrambleHuman:GetPivot().Position
			humanoidRootPart = humanoidRootPart and humanoidRootPart.AssemblyLinearVelocity or Vector3.zero
			local n = position + Vector3.new(humanoidRootPart.X, 0, humanoidRootPart.Z) * 0.15
			local vector = Vector3.new(arg3.Position.X - n.X, 0, arg3.Position.Z - n.Z)
			local vector2 = vector.Magnitude > 1 and vector.Unit * 5 or Vector3.zero
			local slicedn2 = Vector3.new(n.X, arg3.Position.Y, n.Z) + vector2
			local character = localPlayer.Character

			pcall(function()
				character:PivotTo(CFrame.lookAt(slicedn2, Vector3.new(position.X, slicedn2.Y, position.Z)))
			end)

			slicedfn16()
			mech.Status = string.format("Chasing Dr Scramble  |  hits %s / %s", tostring(arg2:GetAttribute("HumanHits") or 0), tostring(arg2:GetAttribute("HumanNeeded") or 3))
			return true
		end

		local function slicedfn21()
			local sliced8 = slicedfn9()
			local sliced9 = tbl4.Root()
			local character = localPlayer.Character
			character = character and character:FindFirstChildOfClass("Humanoid")
			if not sliced8 or not sliced9 then
				return
			end
			local str = tostring(sliced8:GetAttribute("Phase"))
			local n = tonumber(sliced8:GetAttribute("Health")) or 0
			local slicedn2 = tonumber(sliced8:GetAttribute("MaxHealth")) or 0

			if tostring(sliced8:GetAttribute("GrabVictim")) == tostring(localPlayer.UserId) and character then
				character.Jump = true
				slicedfn16()
				mech.Status = "Grabbed, breaking free"
				return
			end

			if str == "Ball" and mech.TryBall and slicedfn19(sliced8, sliced9) then
				return
			end

			if str == "Human" and slicedfn20(sliced8, sliced9) then
				return
			end
			local sliced10, flag = slicedfn18(sliced8)

			if not sliced10 then
				local slicedn3 = (tonumber(sliced8:GetAttribute("SpawnsAt")) or 0) - workspace:GetServerTimeNow()
				mech.Status = slicedn3 > 0 and "In the arena  |  boss spawns in " .. mech.Clock(slicedn3) or string.format("Phase %s, waiting for the boss", str)
				return
			end

			local serverTimeNow = workspace:GetServerTimeNow()
			local slicedn3 = (tonumber(sliced8:GetAttribute("FloorY")) or sliced10.Y) + 3
			local sliced11 = nil
			local sliced12 = nil

			for i = 0, 15 do
				local slicedn4 = i / 16 * 3.1415926535897931 * 2
				local radius = mech.Radius
				local z = sliced10.Z
				local radius2 = mech.Radius
				local vector = Vector3.new(sliced10.X + math.cos(slicedn4) * radius, slicedn3, z + math.sin(slicedn4) * radius2)
				local magnitude = (vector - sliced9.Position).Magnitude

				if slicedfn14(vector, serverTimeNow) or slicedfn14(vector, serverTimeNow + 0.4) then
					magnitude += 10000
				end

				if not sliced11 or magnitude < sliced11 then
					sliced11 = magnitude
					sliced12 = vector
				end
			end

			if sliced12 then
				slicedfn17(sliced12, sliced10)
			end

			slicedfn16()
			flag = flag and flag:GetAttribute("Overheated") == true
			mech.Status = string.format("Fighting %s  |  boss %d / %d%s", str, math.floor(n + 0.5), math.floor(slicedn2 + 0.5), flag and "  |  OVERHEAT" or "")
		end

		local function slicedfn22()
			local sliced8 = slicedfn9()
			local sliced9 = slicedfn12(sliced8 and sliced8:FindFirstChild("LeaveTeleport"))
			if not sliced9 then
				return
			end
			local character = localPlayer.Character

			pcall(function()
				character:PivotTo(CFrame.new(sliced9.Position + Vector3.new(0, 3, 0)))
			end)

			task.wait(0.2)
			slicedfn13(sliced9)
		end

		local function slicedfn23(arg2)
			local sliced8 = slicedfn10()
			local sliced9 = slicedfn12(sliced8)
			if not sliced8 or not sliced9 then
				return false
			end
			local flag = type(tbl4.StealHome) == "function" and tbl4.StealHome() or nil

			if flag and tbl4.InsideBase() then
				local flag2 = mech.Respawned == true
				local n = flag + Vector3.new(0, 3, 0)
				local travelSpeed = flag2 and math.min(mech.TravelSpeed, 300) or mech.TravelSpeed
				local now = os.clock()
				local exitTo = nil

				while true do
					if not (os.clock() - now < 20) then
						exitTo = 1
						break
					else
						if arg2 ~= mech.Generation or not slicedfn8() or slicedfn11() or mech.StealFirst() then
							exitTo = 2
							break
						else
							local sliced10 = tbl4.Root()

							if sliced10 then
								local slicedn2 = n - sliced10.Position

								if slicedn2.Magnitude <= 4 then
									exitTo = 1
									break
								else
									mech.Status = flag2 and "Respawned, going out through the safe zone" or "Leaving the base through the safe zone"
									local magnitude = slicedn2.Magnitude
									local slicedn3 = math.min(travelSpeed * RunService.Heartbeat:Wait(), magnitude)

									pcall(function()
										local rotation = sliced10.CFrame.Rotation
										sliced10.CFrame = CFrame.new(sliced10.Position + slicedn2.Unit * slicedn3) * rotation
										sliced10.AssemblyLinearVelocity = Vector3.zero
									end)

									continue
								end
							end
						end

						break
					end
				end

				if exitTo ~= 1 then
					if exitTo == 2 then
						return false
					end
					return false
				end

				if flag2 then
					mech.Status = "Respawned, resting in the safe zone"
					local slicedn2 = 0

					while slicedn2 < 0.75 do
						local sliced10 = tbl4.Root()

						if sliced10 then
							pcall(function()
								sliced10.AssemblyLinearVelocity = Vector3.zero
							end)
						end

						slicedn2 += RunService.Heartbeat:Wait()
					end
				end
			end

			mech.Respawned = false
			local position = sliced9.Position
			local now = os.clock()
			local exitTo2 = nil
			local sliced10

			while true do
				if not (os.clock() - now < 60) then
					exitTo2 = 1
					break
				else
					if arg2 ~= mech.Generation or not slicedfn8() or slicedfn11() or mech.StealFirst() then
						exitTo2 = 1
						break
					else
						sliced10 = tbl4.Root()

						if not sliced10 then
							exitTo2 = 2
							break
						else
							local vector = Vector3.new(position.X - sliced10.Position.X, 0, position.Z - sliced10.Position.Z)

							if not (vector.Magnitude <= 14) then
								local n = vector.Unit * math.min(mech.TravelSpeed, vector.Magnitude / 0.05)
								mech.Status = string.format("Going to the Mech portal, %d studs", math.floor(vector.Magnitude + 0.5))

								pcall(function()
									sliced10.AssemblyLinearVelocity = Vector3.new(n.X, sliced10.AssemblyLinearVelocity.Y, n.Z)
								end)

								RunService.Heartbeat:Wait()
								continue
							end
						end
					end

					break
				end
			end

			if exitTo2 ~= 1 then
				if exitTo2 == 2 then
					return false
				end

				pcall(function()
					sliced10.AssemblyLinearVelocity = Vector3.zero
				end)

				slicedfn13(sliced9)
				task.wait(0.4)

				if not slicedfn11() then
					pcall(function()
						local rfScrambleBossEnterArena = networking:FindFirstChild("RF/ScrambleBoss/EnterArena")

						if rfScrambleBossEnterArena then
							rfScrambleBossEnterArena:InvokeServer()
						end
					end)
				end
			end

			local now2 = os.clock()

			while not slicedfn11() and os.clock() - now2 < 5 do
				task.wait(0.1)
			end

			return slicedfn11()
		end

		local function slicedfn24()
			mech.Busy = true
			mech.Generation = mech.Generation + 1
			local generation = mech.Generation
			tbl4.Shield("mech", true)

			pcall(function()
				if tbl4.Treadmill and tbl4.Treadmill.Riding or type(tbl4.OnBelt) == "function" and tbl4.OnBelt() then
					tbl4.ExitBelt()
				end
			end)

			if not slicedfn11() and not mech.StealFirst() then
				pcall(slicedfn23, generation)
			end

			while generation == mech.Generation and slicedfn8() and slicedfn11() and not mech.StealFirst() do
				local str = slicedfn9()
				str = str and tostring(str:GetAttribute("Phase")) or ""

				if str == "Defeated" or str == "Final" or str == "Ended" or str == "Won" then
					mech.Status = "Dr Scramble defeated, going back home"
					mech.DefeatedAt = mech.DefeatedAt or os.clock()
					local leave = mech.Leave

					if leave then
						local defeatedAt = mech.DefeatedAt
						leave = os.clock() - defeatedAt > 15
					end

					if leave then
						pcall(slicedfn22)
						task.wait(2)
					else
						task.wait(0.3)
					end
				else
					pcall(slicedfn21)
					RunService.Heartbeat:Wait()
				end
			end

			if slicedfn11() and mech.StealFirst() then
				mech.Status = tostring(mech.StealFirst()) .. ", leaving the arena"
				pcall(slicedfn22)
				local n = 0

				while slicedfn11() and n < 5 do
					n += task.wait(0.2)
				end
			end

			mech.DefeatedAt = nil
			mech.Run = nil
			tbl4.Shield("mech", false)
			tbl4.ReleaseMovement("mech")
			mech.Busy = false
			tbl3.Wake()
		end

		pcall(function()
			local reScrambleBossHazard = networking:FindFirstChild("RE/ScrambleBoss/Hazard")

			if reScrambleBossHazard and reScrambleBossHazard:IsA("RemoteEvent") then
				table.insert(mech.Links, reScrambleBossHazard.OnClientEvent:Connect(function(arg2)
					if type(arg2) == "table" then
						mech.Hazards[arg2.Id or #mech.Hazards + 1] = arg2
					end
				end))
			end
		end)

		table.insert(mech.Links, localPlayer.CharacterAdded:Connect(function()
			mech.Respawned = true
		end))

		mech.Row = arg:CreateText({ Name = "Mech Status", Text = "Idle" })

		mech.Handle = arg:CreateToggle({
			Name = "Auto Mech Boss",
			Default = false,
			Callback = function()
				if not slicedfn8() then
					mech.Generation = mech.Generation + 1
				end

				tbl3.Wake()
			end,
		})

		for _, sliced8 in ipairs({
			{ "Mech Tween Speed", 100, 1000, 250, 10, "studs/s", "TravelSpeed" },
			{ "Main Weapon Hold", 0, 1.5, 0.3, 0.01, "s", "MainHold" },
			{ "Scrambler Hold", 0, 1.5, 0.4, 0.01, "s", "SecondHold" },
		}) do
			arg:CreateSlider({
				Name = sliced8[1],
				Min = sliced8[2],
				Max = sliced8[3],
				Default = sliced8[4],
				Increment = sliced8[5],
				Unit = sliced8[6],
				SubOf = mech.Handle,
				Callback = function(arg2)
					mech[sliced8[7]] = math.clamp(tonumber(arg2) or sliced8[4], sliced8[2], sliced8[3])
				end,
			})
		end

		for _, sliced8 in ipairs({
			{ "Swap Two Weapons", "SwapTools" },
			{ "Dodge Attacks", "Dodge" },
			{ "Ball And Core Phase", "TryBall" },
			{ "Leave After Fight", "Leave" },
		}) do
			arg:CreateToggle({
				Name = sliced8[1],
				Default = true,
				SubOf = mech.Handle,
				Callback = function(arg2)
					mech[sliced8[2]] = arg2 ~= false
				end,
			})
		end

		tbl3.Add(function()
			local row = mech.Row

			if not slicedfn8() then
				mech.Status = "Off  |  " .. mech.Timer()
			elseif not mech.Busy then
				if slicedfn11() then
					mech.Status = "In the arena"
				else
					mech.Status = mech.Timer()
				end
			end

			if row and mech.Shown ~= mech.Status and type(row.Set) == "function" then
				mech.Shown = mech.Status
				pcall(row.Set, row, mech.Status)
			end

			local invisibilityHandle = tbl4.InvisibilityHandle
			local flag = invisibilityHandle ~= nil and tbl4.Toggle(invisibilityHandle, false)

			if slicedfn8() and (mech.Busy or slicedfn11() or slicedfn10()) then
				mech.InvisResumeAt = nil

				if not tbl4.InvisMech then
					tbl4.InvisMech = true

					if flag then
						tbl4.Notify("Invisibility", "Invisibility is paused for the Mech boss and comes back after it.")
					end
				end
			elseif tbl4.InvisMech and not mech.Busy then
				mech.InvisResumeAt = mech.InvisResumeAt or os.clock() + 5

				if mech.InvisResumeAt <= os.clock() then
					mech.InvisResumeAt = nil
					tbl4.InvisMech = false

					if flag then
						tbl4.Notify("Invisibility", "The Mech boss is over, Invisibility is back on.")
					end
				end
			end

			if not slicedfn8() or mech.Busy then
				return true
			end

			if slicedfn11() or slicedfn10() then
				local sliced8 = mech.StealFirst()
				if sliced8 then
					mech.Status = sliced8 .. "  |  " .. mech.Timer()
					return true
				end
				local character = localPlayer.Character
				if character and character:GetAttribute("InvisApplied") == true then
					mech.Status = "Leaving Invisibility for the boss"
					return true
				end

				if not tbl4.ClaimMovement("mech") then
					mech.Status = "Waiting for " .. tostring(tbl4.Movement.Owner or "movement")
					return true
				end
				task.spawn(slicedfn24)
				return true
			end

			return true
		end)

		slicedfn4(function()
			tbl4.InvisMech = false
			mech.Generation = mech.Generation + 1

			for _, link in ipairs(mech.Links) do
				pcall(function()
					link:Disconnect()
				end)
			end

			pcall(tbl4.Shield, "mech", false)
			pcall(tbl4.ReleaseMovement, "mech")
		end)
	end

	tbl4.MechBoot(sliced6)

	do
		local n = 5
		local slicedn2 = 5
		local sliced8 = nil
		local sliced9 = nil
		local flag = false
		local slicedn3 = 0
		local slicedn4 = 0
		local slicedn5 = 0
		local sliced10 = nil
		local slicedn6 = 0
		local str = ""
		local flag2 = false

		local function slicedfn8(arg, arg2)
			local sliced11 = networking:FindFirstChild(arg)
			if not sliced11 or not sliced11:IsA("RemoteFunction") then
				return false, nil, nil
			end

			if arg2 == nil then
				return pcall(sliced11.InvokeServer, sliced11)
			end
			return pcall(sliced11.InvokeServer, sliced11, arg2)
		end

		local function slicedfn9()
			local save2 = tbl.Save
			if type(save2) ~= "table" or type(save2.Get) ~= "function" then
				return nil
			end
			local ok, result = pcall(save2.Get)
			return ok and type(result) == "table" and result or nil
		end

		local function slicedfn10(arg)
			local directory = tbl.Assets and tbl.Assets.Directory
			local flag3 = type(directory) == "table" and directory[tostring(arg)] or nil
			return tostring(type(flag3) == "table" and flag3.DisplayName or arg)
		end

		local function slicedfn11(arg)
			if not arg and type(sliced10) == "table" and os.clock() < slicedn5 then
				return sliced10
			end
			slicedn5 = os.clock() + slicedn2
			local AskState, sliced11 = slicedfn8("RF/ScrambleTradeIn/AskState")

			if AskState and type(sliced11) == "table" then
				sliced10 = sliced11
				slicedn6 = os.clock()
			end

			return sliced10
		end

		local function slicedfn12(arg, arg2)
			local requirements = type(arg) == "table" and arg.Requirements or nil
			if type(requirements) ~= "table" or #requirements == 0 then
				return nil, "No active recipe"
			end
			local tbl10 = {}

			if type(arg2.EquippedAssets) == "table" then
				for _, equippedAsset in pairs(arg2.EquippedAssets) do
					tbl10[equippedAsset] = true
				end
			end

			local tbl11 = {}

			for _, requirement in ipairs(requirements) do
				tbl11[tostring(requirement)] = {}
			end

			local pairs = pairs
			local inventory = arg2.Inventory or {}

			for k, sliced12 in pairs(inventory) do
				local flag3 = type(sliced12) == "table" and tbl11[tostring(sliced12.Category)] or nil

				if flag3 and sliced12.InFuse ~= true and sliced12.IsFavorite ~= true and not tbl10[k] then
					local flag4 = type(sliced12.Mutations) == "table" and next(sliced12.Mutations) ~= nil
					table.insert(flag3, { Uid = k, Scale = tonumber(sliced12.Scale) or 0, Mutated = flag4 })
				end
			end

			for _, sliced12 in pairs(tbl11) do
				table.sort(sliced12, function(arg3, arg4)
					if arg3.Mutated ~= arg4.Mutated then
						return arg4.Mutated
					end
					return arg3.Scale < arg4.Scale
				end)
			end

			local tbl12 = {}
			local tbl13 = {}

			for _, requirement in ipairs(requirements) do
				local tbl14 = tbl11[tostring(requirement)]
				local ipairs = ipairs
				tbl14 = tbl14 or {}
				local sliced13 = nil

				for _, sliced14 in ipairs(tbl14) do
					if not tbl13[sliced14.Uid] then
						sliced13 = sliced14
						break
					else
						sliced13 = nil
					end
				end

				if not sliced13 then
					return nil, "Missing " .. slicedfn10(requirement)
				end
				tbl13[sliced13.Uid] = true
				table.insert(tbl12, sliced13.Uid)
			end

			return tbl12
		end

		local function slicedfn13()
			local sliced11 = sliced10
			if type(sliced11) ~= "table" then
				return "Lab status unknown"
			end

			if sliced11.Unlocked ~= true then
				return "Lab is locked on this account"
			end
			local tbl10 = {}
			local ipairs = ipairs
			local requirements = sliced11.Requirements or {}

			for _, requirement in ipairs(requirements) do
				table.insert(tbl10, slicedfn10(requirement))
			end

			local slicedn7 = (tonumber(sliced11.SecondsUntilRotation) or 0) - (os.clock() - slicedn6)

			if slicedn7 < 0 then
				slicedn7 = 0
			end

			local str2 = string.format("%s  -  needs %s  -  pity %s/%s  -  free rerolls %s  -  rotates in %d:%02d", tostring(sliced11.BannerDisplayName or sliced11.BannerId or "Lab"), #tbl10 > 0 and table.concat(tbl10, ", ") or "unknown", tostring(sliced11.PityCount or 0), tostring(sliced11.PityThreshold or 0), tostring(sliced11.FreeRefreshesRemaining or 0), math.floor(slicedn7 / 60), math.floor(slicedn7 % 60))

			if str ~= "" then
				str2 ..= "  -  " .. str
			end

			return str2
		end

		local function slicedfn14(arg)
			local sliced11 = slicedfn11(true)
			if type(sliced11) ~= "table" or sliced11.Unlocked ~= true then
				return
			end

			if sliced11.PendingReward ~= nil and sliced11.PendingReward ~= false then
				local AskFinishReveal, sliced12 = slicedfn8("RF/ScrambleTradeIn/AskFinishReveal")
				str = AskFinishReveal and sliced12 ~= false and "Reward claimed" or "Reward claim failed"
				slicedn5 = 0
				return
			end

			local sliced12 = slicedfn9()
			if not sliced12 then
				return
			end
			local sliced13, sliced14 = slicedfn12(sliced11, sliced12)

			if not sliced13 then
				str = sliced14 or "Recipe not ready"
				local flag3 = arg == slicedn3 and tbl4.Toggle(sliced9, false)

				if flag3 then
					flag3 = (tonumber(sliced11.FreeRefreshesRemaining) or 0) > 0
				end

				if flag3 then
					local AskRefresh, sliced15, sliced16 = slicedfn8("RF/ScrambleTradeIn/AskRefresh")

					if AskRefresh and sliced15 ~= false then
						str = "Recipe rerolled"
					else
						str = tostring(sliced16 or "Reroll rejected")
					end

					slicedn5 = 0
				end

				return
			end

			if not tbl4.Toggle(sliced8, false) then
				str = "Ready to trade in"
				return
			end

			if arg ~= slicedn3 then
				return
			end
			local AskTradeIn, sliced15, sliced16 = slicedfn8("RF/ScrambleTradeIn/AskTradeIn", sliced13)

			if AskTradeIn and sliced15 ~= false then
				str = "Trade-in sent"
			else
				str = tostring(sliced16 or "Trade rejected")
			end

			slicedn5 = 0
		end

		local sliced11 = sliced6:CreateText({ Name = "Lab Status", Text = "Loading Lab data..." })

		sliced8 = sliced6:CreateToggle({
			Name = "Auto Lab Trade-In",
			Default = false,
			Callback = function()
				slicedn3 += 1
				str = ""
				slicedn4 = 0
				slicedn5 = 0
				tbl3.Wake()
			end,
		})

		sliced9 = sliced6:CreateToggle({
			Name = "Auto Reroll Lab Recipe",
			Default = false,
			Callback = function()
				slicedn3 += 1
				str = ""
				slicedn4 = 0
				slicedn5 = 0
				tbl3.Wake()
			end,
		})

		for _, sliced12 in ipairs({
			{ Key = "Place", Name = "Place Lab Recipe Eggs" },
			{ Key = "Hatch", Name = "Hatch Lab Recipe Eggs" },
		}) do
			local key = sliced12.Key

			tbl4.Rift.Handles[key] = sliced6:CreateToggle({
				Name = sliced12.Name,
				Default = false,
				Callback = function()
					tbl4.Rift.Next = 0
					local sliced13 = tbl4.Rift.Restart[key]

					if type(sliced13) == "function" then
						sliced13()
					end

					tbl3.Wake()
				end,
			})
		end

		tbl3.Add(function()
			local sliced12 = tbl4.Toggle(sliced8, false)
			local sliced13 = tbl4.Toggle(sliced9, false)
			local slicedn7 = (sliced12 or sliced13) and 5 or 30

			if not flag2 and (sliced10 == nil or slicedn5 == 0 or os.clock() - slicedn6 >= slicedn7) then
				flag2 = true

				task.spawn(function()
					pcall(slicedfn11, true)
					flag2 = false
				end)
			end

			if sliced11 and type(sliced11.Set) == "function" then
				pcall(sliced11.Set, sliced11, slicedfn13())
			end

			local flag3 = flag

			if not flag then
				flag3 = not (sliced12 or sliced13)
			end

			if flag3 or os.clock() < slicedn4 then
				return false
			end
			flag = true
			slicedn4 = os.clock() + n
			local sliced14 = slicedn3

			task.spawn(function()
				pcall(slicedfn14, sliced14)
				flag = false
				tbl3.Wake()
			end)

			return false
		end)
	end

	local n = 6
	local slicedn2 = 1.5
	local slicedn3 = 400
	local tbl10, tbl11, tbl12, tbl13, slicedn4, snapshot, slicedn5, flag, slicedn6, slicedn7
	local str, str2, tbl14, slicedn8, flag2, tbl15, tbl16, flag3, slicedn9, sliced8
	local slicedfn8, slicedfn9, slicedfn10, slicedfn11, slicedfn12, slicedfn13, slicedfn14, slicedfn15, slicedfn16, slicedfn17
	local slicedfn18, slicedfn19, slicedfn20, slicedfn21, slicedfn22, slicedfn23, slicedfn24, slicedfn25, slicedfn26, slicedfn27
	local slicedfn28, slicedfn29, slicedfn30, slicedfn31

	do
		local vector = Vector3.new(2120, -120, -355)
		tbl10 = { "LostPart1", "LostPart2" }

		tbl11 = {
			{ Label = "Experiment #001", Id = "LimitedTimeExperimentPet" },
			{ Label = "Nibbles #013", Id = "Nibbles013" },
			{ Label = "Scrambled Mutation", Id = "MutationConsumable" },
			{ Label = "2x Cash Booster", Id = "CashBooster" },
			{ Label = "1.25x Speed", Id = "SpeedBoost" },
			{ Label = "2x Treadmill Booster", Id = "TreadmillBooster" },
		}

		local tbl17 = {}

		for _, sliced9 in ipairs(tbl11) do
			tbl17[#tbl17 + 1] = sliced9.Label
		end

		tbl12 = {}
		tbl13 = {}
		slicedn4 = 0
		local tbl18 = { ["Experiment #001"] = true, ["Nibbles #013"] = true, ["Scrambled Mutation"] = true }
		snapshot = nil
		slicedn5 = -math.huge
		flag = false
		slicedn6 = 0
		slicedn7 = 0
		str = ""
		str2 = ""
		tbl14 = { Tool = nil, EquipAt = 0 }
		slicedn8 = 16
		flag2 = false
		tbl15 = { Index = 1, Since = 0, Tool = nil }
		tbl16 = { Latch = false, Ended = false }
		flag3 = false
		slicedn9 = 0
		sliced8 = nil

		local function slicedfn32()
			local packages = ReplicatedStorage:FindFirstChild("Packages")
			packages = packages and packages:FindFirstChild("Networking")
			packages = packages and packages:FindFirstChild("RF/Scramble/Request")
			if packages and packages:IsA("RemoteFunction") then
				return packages
			end
			return nil
		end

		slicedfn8 = function(arg, ...)
			local sliced9 = slicedfn32()
			if not sliced9 then
				return nil
			end
			local sliced10 = table.pack(...)

			local ok, result = pcall(function()
				return sliced9:InvokeServer(arg, table.unpack(sliced10, 1, sliced10.n))
			end)

			if not ok or type(result) ~= "table" then
				return nil
			end

			if type(result.Snapshot) == "table" then
				snapshot = result.Snapshot
				slicedn5 = os.clock()
			elseif arg == "Snapshot" and type(result.State) == "table" then
				snapshot = result
				slicedn5 = os.clock()
			end

			return result
		end

		slicedfn9 = function(arg)
			if arg or snapshot == nil or os.clock() - slicedn5 >= n then
				slicedfn8("Snapshot")
			end

			return snapshot
		end

		slicedfn10 = function()
			local sliced9 = snapshot
			return type(sliced9) == "table" and type(sliced9.State) == "table" and sliced9.State or nil
		end

		slicedfn11 = function()
			local sliced9 = snapshot
			if type(sliced9) ~= "table" or sliced9.Enabled == false or type(sliced9.State) ~= "table" then
				return false
			end
			local num = tonumber(sliced9.EventEndsAt)
			return num == nil or workspace:GetServerTimeNow() < num
		end

		slicedfn12 = function()
			local sliced9 = snapshot
			local window = type(sliced9) == "table" and sliced9.Window or nil
			if type(window) ~= "table" then
				return false, nil
			end
			local serverTimeNow = workspace:GetServerTimeNow()
			local num = tonumber(window.StartsAt)
			local num2 = tonumber(window.EndsAt)
			local flag4 = window.Active == true
			local flag5

			if flag4 then
				flag5 = flag4
			else
				flag5 = num and num2 and serverTimeNow >= num and serverTimeNow < num2
			end

			if flag5 then
				return true, num2 and math.max(0, num2 - serverTimeNow) or nil
			end
			local num3 = tonumber(window.NextAt)
			return false, num3 and math.max(0, num3 - serverTimeNow) or nil
		end

		slicedfn13 = function(arg, arg2)
			local lostParts = type(arg) == "table" and arg.LostParts or nil
			if type(lostParts) ~= "table" then
				return false
			end

			if lostParts[arg2] then
				return true
			end

			for _, lostPart in pairs(lostParts) do
				if lostPart == arg2 then
					return true
				end
			end

			return false
		end

		slicedfn14 = function(arg)
			local slicedn10 = 0

			for _, sliced9 in ipairs(tbl10) do
				if slicedfn13(arg, sliced9) then
					slicedn10 += 1
				end
			end

			return slicedn10
		end

		local function slicedfn33(arg)
			local slicedn10 = math.max(0, math.floor(tonumber(arg) or 0))
			if slicedn10 >= 3600 then
				return string.format("%dh %dm", slicedn10 // 3600, slicedn10 % 3600 // 60)
			end
			return string.format("%dm %ds", slicedn10 // 60, slicedn10 % 60)
		end

		slicedfn15 = function()
			local sliced9 = slicedfn10()
			if not sliced9 then
				return "Dr Scramble event is not running"
			end

			if not slicedfn11() then
				return "Dr Scramble event has ended"
			end
			local sliced10, sliced11 = slicedfn12()
			local str3

			if sliced10 then
				str3 = "Outbreak live " .. slicedfn33(sliced11 or 0)
			else
				str3 = sliced10
			end

			str3 = str3 or (sliced11 and "Outbreak in " .. slicedfn33(sliced11) or "Outbreak soon")
			local str4 = sliced9.Completed == true and "Vault claimed"

			if not str4 then
				str4 = string.format("Lost %d/2  Drone %d/3", slicedfn14(sliced9), math.min(3, tonumber(sliced9.DroneParts) or 0))
			end

			if sliced10 then
				local slicedn10 = 0

				for _, sliced12 in pairs(tbl12) do
					if (tonumber(sliced12.Health) or 0) > 0 then
						slicedn10 += 1
					end
				end

				str3 ..= string.format("  %d drones", slicedn10)
			end

			local str5 = string.format("Samples %d  -  %s  -  %s", tonumber(sliced9.Samples) or 0, str4, str3)

			if str2 ~= "" and tbl4.Toggle(nil, false) then
				str5 ..= "  -  " .. str2
			end

			if str ~= "" then
				str5 ..= "  -  " .. str
			end

			return str5
		end

		slicedfn16 = function()
			return tbl4.Root()
		end

		slicedfn17 = function(arg, arg2, arg3, arg4)
			local slicedn10 = arg4 or 400
			local sliced9 = slicedfn16()
			if not sliced9 then
				return false
			end
			arg3 = arg3 or 1
			if (sliced9.Position - arg).Magnitude <= arg3 then
				return true
			end
			tbl4.Shield("scramble", true)
			local slicedn11 = os.clock() + 6

			while not tbl4.Swapped() and os.clock() < slicedn11 and not arg2() do
				str = "Waiting for the character to settle"
				RunService.Heartbeat:Wait()
			end

			local sliced10 = slicedfn16() or sliced9
			local character = localPlayer.Character
			tbl4.Driving = tbl4.Driving + 1
			local position = sliced10.Position
			local flag4 = nil
			local slicedn12 = (arg - position).Magnitude / slicedn10 + 3
			local slicedn13 = 0

			local connection = RunService.Heartbeat:Connect(function(deltaTime)
				if flag4 ~= nil or tbl4.AntiGuard.Busy then
					return
				end
				slicedn13 += deltaTime
				local sliced11 = slicedfn16()
				if not sliced11 or arg2() or slicedn13 > slicedn12 or localPlayer.Character ~= character then
					flag4 = false
					return
				end

				if (sliced11.Position - position).Magnitude > 8 then
					position = sliced11.Position
				end

				local slicedn14 = arg - position
				local slicedn15 = slicedn10 * deltaTime
				local flag5 = slicedn14.Magnitude <= math.max(slicedn15, arg3)
				position = flag5 and arg or position + slicedn14.Unit * slicedn15
				local vector2 = Vector3.new(slicedn14.X, 0, slicedn14.Z)
				local cframe = vector2.Magnitude > 0.05 and CFrame.lookAt(Vector3.zero, vector2.Unit) or sliced11.CFrame.Rotation

				pcall(function()
					sliced11.CFrame = CFrame.new(position) * cframe
					sliced11.AssemblyLinearVelocity = Vector3.zero
					sliced11.AssemblyAngularVelocity = Vector3.zero
				end)

				if flag5 then
					flag4 = true
				end
			end)

			while flag4 == nil do
				RunService.Heartbeat:Wait()
			end

			connection:Disconnect()
			tbl4.Driving = math.max(0, tbl4.Driving - 1)
			tbl4.Shield("scramble", false)
			return flag4
		end

		slicedfn18 = function(arg)
			if typeof(arg) ~= "Instance" or not arg:IsA("ProximityPrompt") then
				return false
			end

			local ok = pcall(function()
				arg:InputHoldBegin()
				local slicedn10 = tonumber(type(tbl4.PromptHold) == "function" and tbl4.PromptHold(arg) or arg.HoldDuration) or 0

				if slicedn10 > 0 then
					task.wait(slicedn10 + 0.2)
				end

				arg:InputHoldEnd()
			end)

			if not ok and type(fireproximityprompt) == "function" then
				ok = pcall(fireproximityprompt, arg)
			end

			return ok
		end

		local function slicedfn34()
			local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
			local secretZones = world and world:FindFirstChild("SecretZones")
			return secretZones and secretZones:FindFirstChild("Cave") or nil
		end

		slicedfn19 = function(arg)
			local sliced9 = slicedfn34()
			local teleporter = sliced9 and sliced9:FindFirstChild("Teleporter")
			teleporter = teleporter and teleporter:FindFirstChild(arg)
			teleporter = teleporter and teleporter:FindFirstChild("SecretZonePrompt", true)
			return teleporter and teleporter:IsA("ProximityPrompt") and teleporter or nil
		end

		slicedfn20 = function(arg, arg2)
			arg = arg and arg.Parent
			if arg and arg:IsA("Attachment") then
				return arg.WorldPosition
			end

			if arg and arg:IsA("BasePart") then
				return arg.Position
			end
			return arg2
		end

		slicedfn21 = function()
			local sliced9 = slicedfn16()
			if not sliced9 then
				return false
			end
			local position = sliced9.Position
			local vector2 = Vector3.new(position.X - vector.X, 0, position.Z - vector.Z)
			return position.Y < -60 and vector2.Magnitude < 160
		end

		local function slicedfn35()
			local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
			world = world and world:FindFirstChild("Areas")
			world = world and world:FindFirstChild("SeparationLine")
			return world and world:IsA("BasePart") and world.Position.X or 552
		end

		slicedfn22 = function(arg)
			if not arg then
				arg = slicedfn16()
				arg = arg and arg.Position
			end

			return arg ~= nil and arg.X < slicedfn35()
		end

		local connection = localPlayer.CharacterAdded:Connect(function()
			tbl4.ScrambleRespawned = true
			tbl14.Tool = nil
			tbl14.EquipAt = 0
		end)

		slicedfn4(function()
			pcall(function()
				connection:Disconnect()
			end)
		end)

		slicedfn23 = function(arg, arg2)
			if not slicedfn22() then
				tbl4.ScrambleRespawned = false
				return true
			end

			if arg2 and slicedfn22(arg2) then
				return true
			end

			local function slicedfn36()
				str = "Respawned, resting in the safe zone"
				local slicedn10 = os.clock() + 0.75

				while os.clock() < slicedn10 do
					if arg() then
						return false
					end
					task.wait(0.1)
				end

				tbl4.ScrambleRespawned = false
				return true
			end

			local flag4 = type(tbl4.StealHome) == "function" and tbl4.StealHome() or nil
			if not flag4 then
				tbl4.ScrambleRespawned = false
				return true
			end
			local flag5 = tbl4.ScrambleRespawned == true

			if tbl4.DistanceTo(flag4) <= 12 then
				if flag5 then
					return (slicedfn36())
				end
				return true
			end

			str = flag5 and "Respawned, easing out through the safe zone" or "Leaving the base through the safe zone"
			local sliced9 = slicedfn17
			local sliced10 = sliced9(flag4 + Vector3.new(0, 3, 0), arg, 3, flag5 and math.min(400, 300) or nil)
			if sliced10 and flag5 then
				return (slicedfn36())
			end
			return sliced10
		end

		local function slicedfn36(arg, arg2, arg3)
			local sliced9 = slicedfn16()
			if not sliced9 then
				return false
			end
			tbl4.Shield("scramblefly", true)
			local position = sliced9.Position
			local flag4 = true

			if Vector3.new(arg.X - position.X, 0, arg.Z - position.Z).Magnitude > 250 then
				local slicedn10 = math.max(position.Y, arg.Y, 98)
				flag4 = slicedfn17(Vector3.new(position.X, slicedn10, position.Z), arg2, 2) and slicedfn17(Vector3.new(arg.X, slicedn10, arg.Z), arg2, 2)
			end

			flag4 = flag4 and slicedfn17(arg, arg2, math.min(arg3, 2))
			tbl4.Shield("scramblefly", false)
			return flag4
		end

		local function slicedfn37()
			local flag4 = type(tbl4.StealHome) == "function" and tbl4.StealHome() or nil
			return flag4 and flag4 + Vector3.new(0, 3, 0) or nil
		end

		slicedfn24 = function(arg, arg2, arg3)
			local slicedn10 = arg3 or 6
			if tbl4.DistanceTo(arg) <= slicedn10 then
				return true
			end
			local sliced9 = slicedfn22()
			local sliced10 = slicedfn22(arg)

			if sliced9 and not sliced10 then
				if not slicedfn23(arg2, arg) then
					return false
				end
			elseif sliced10 and not sliced9 then
				local sliced11 = slicedfn37()

				if sliced11 and (sliced11 - arg).Magnitude > 12 and tbl4.DistanceTo(sliced11) > 12 then
					str = "Coming back through the safe zone"
					if not slicedfn36(sliced11, arg2, 3) then
						return false
					end
				end
			end

			return slicedfn36(arg, arg2, slicedn10)
		end

		slicedfn25 = function(arg)
			if slicedfn22() or arg() or tbl4.IsNight() or tbl4.WallSealed() then
				return
			end
			local sliced9 = slicedfn37()

			if sliced9 then
				str = "Coming back through the safe zone"
				slicedfn24(sliced9, arg, 4)
			end
		end

		local function slicedfn38(arg)
			if slicedfn21() then
				return true
			end
			local Entry = slicedfn19("Entry")
			local sliced9 = slicedfn20(Entry, Vector3.new(2125.7, 73.1, -295.4))
			str = "Flying to the Secret Cave"
			if not slicedfn24(sliced9, arg, 6) then
				return false
			end

			for i = 1, 4 do
				if arg() then
					return false
				end
				str = "Entering the Secret Cave"
				slicedfn18(Entry or slicedfn19("Entry"))
				local slicedn10 = os.clock() + 1.5

				while os.clock() < slicedn10 and not slicedfn21() do
					RunService.Heartbeat:Wait()
				end

				if slicedfn21() then
					return true
				end
			end

			str = "Cave door missed, flying in"
			local quest = type(snapshot) == "table" and snapshot.Quest or nil
			local position = type(quest) == "table" and type(quest.EscapedExperiment) == "table" and quest.EscapedExperiment.Position or nil

			if typeof(position) == "Vector3" then
				pcall(tbl4.FlyTo, position, arg, "scramble")
			end

			return slicedfn21()
		end

		local function slicedfn39(arg)
			local quest = type(snapshot) == "table" and snapshot.Quest or nil
			local flag4 = type(quest) == "table" and quest[arg] or nil
			local position = type(flag4) == "table" and flag4.Position or nil
			if typeof(position) == "Vector3" then
				return position
			end
			local drScrambleEvent = workspace:FindFirstChild("DrScrambleEvent")
			drScrambleEvent = drScrambleEvent and drScrambleEvent:FindFirstChild(arg)
			if drScrambleEvent and drScrambleEvent:IsA("Model") then
				return drScrambleEvent:GetPivot().Position
			end
			return nil
		end

		local function slicedfn40(arg)
			local sliced9 = snapshot
			local interactions = type(sliced9) == "table" and sliced9.Interactions or nil
			return math.max(4, (type(interactions) == "table" and tonumber(interactions[arg]) or 12) - 4)
		end

		slicedfn26 = function(arg)
			local sliced9 = slicedfn10()
			if not sliced9 or sliced9.Discovered == true then
				return true
			end
			local EscapedExperiment = slicedfn39("EscapedExperiment")
			if not EscapedExperiment or not slicedfn38(arg) then
				return false
			end
			str = "Talking to the Escaped Experiment"
			if not slicedfn17(EscapedExperiment, arg, slicedfn40("NpcRadius")) then
				return false
			end
			local Discover = slicedfn8("Discover")
			slicedfn9(true)
			return Discover ~= nil and slicedfn10() ~= nil and slicedfn10().Discovered == true
		end

		slicedfn27 = function(arg)
			local sliced9 = slicedfn10()
			local flag4 = not sliced9 or sliced9.Completed == true
			local flag5

			if flag4 then
				flag5 = flag4
			else
				local slicedn10 = #tbl10
				flag5 = slicedfn14(sliced9) >= slicedn10
			end

			if flag5 then
				return
			end

			if sliced9.Discovered ~= true and not slicedfn26(arg) then
				return
			end

			for _, sliced10 in ipairs(tbl10) do
				if arg() then
					return
				end

				if not slicedfn13(slicedfn10(), sliced10) then
					local drScrambleEvent = workspace:FindFirstChild("DrScrambleEvent")
					local hitbox = drScrambleEvent and drScrambleEvent:FindFirstChild(sliced10)
					hitbox = hitbox and hitbox:FindFirstChild("Hitbox", true)
					local claimLostPart = hitbox and hitbox:FindFirstChild("ClaimLostPart", true)
					local position = hitbox and hitbox:IsA("BasePart") and hitbox.Position or slicedfn39(sliced10)

					if position then
						str = "Flying to " .. (sliced10 == "LostPart1" and "Lost Part 1" or "Lost Part 2")

						if slicedfn24(position + Vector3.new(0, 2, 0), arg, 3) then
							str = "Collecting the lost part"
							local slicedn10 = position + Vector3.new(0, 2.5, 0)
							local character = localPlayer.Character
							tbl4.Shield("scramble", true)
							tbl4.Driving = tbl4.Driving + 1

							local connection2 = RunService.Heartbeat:Connect(function()
								local sliced11 = tbl4.Root()
								if not sliced11 or sliced11.Parent ~= character or tbl4.AntiGuard.Busy or tbl4.Movement.Owner ~= "scramble" then
									return
								end

								pcall(function()
									local rotation = sliced11.CFrame.Rotation
									sliced11.CFrame = CFrame.new(slicedn10) * rotation
									sliced11.AssemblyLinearVelocity = Vector3.zero
									sliced11.AssemblyAngularVelocity = Vector3.zero
								end)
							end)

							for i = 1, 4 do
								if not arg() then
									claimLostPart = claimLostPart or hitbox and hitbox:FindFirstChild("ClaimLostPart", true)
									slicedfn18(claimLostPart)
									task.wait(0.6)
									slicedfn9(true)
									if not slicedfn13(slicedfn10(), sliced10) then
										continue
									end
								end

								break
							end

							connection2:Disconnect()
							tbl4.Driving = math.max(0, tbl4.Driving - 1)
							tbl4.Shield("scramble", false)
							if arg() then
								return
							end
							continue
						end
					end
				end
			end
		end

		slicedfn28 = function(arg)
			local sliced9 = slicedfn10()
			if not sliced9 or sliced9.Completed == true then
				return
			end
			local num = tonumber(sliced9.TotalParts)

			if not num then
				num = slicedfn14(sliced9) + (tonumber(sliced9.DroneParts) or 0)
			end

			if num < 5 then
				return
			end
			local ExperimentVault = slicedfn39("ExperimentVault")
			if not ExperimentVault or not slicedfn38(arg) then
				return
			end
			str = "Opening the Experiment Vault"
			if not slicedfn17(ExperimentVault, arg, slicedfn40("VaultRadius")) then
				return
			end
			slicedfn8("Vault")
			slicedfn9(true)
			local sliced10 = slicedfn10()

			if sliced10 and sliced10.Completed == true then
				str = "Vault opened, The Scrambler unlocked"
			end
		end

		slicedfn29 = function()
			local function slicedfn41(arg)
				if not arg or not arg:IsA("Tool") then
					return false
				end

				if tostring(arg:GetAttribute("ItemType")) ~= "MutationConsumable" then
					return false
				end
				local attribute = arg:GetAttribute("MutationId") or arg:GetAttribute("MutationTemplate")
				if attribute ~= nil then
					return tostring(attribute) == "Scrambled"
				end
				return string.find(string.lower(arg.Name), "scrambled", 1, true) ~= nil
			end

			local character = localPlayer.Character

			if character then
				for _, child in ipairs(character:GetChildren()) do
					if slicedfn41(child) then
						return child, true
					end
				end
			end

			local backpack = localPlayer:FindFirstChildOfClass("Backpack")

			if backpack then
				for _, child in ipairs(backpack:GetChildren()) do
					if slicedfn41(child) then
						return child, false
					end
				end
			end

			return nil, false
		end

		slicedfn30 = function(arg, arg2)
			local shopPurchases = type(arg) == "table" and arg.ShopPurchases or nil
			local flag4 = type(shopPurchases) == "table" and shopPurchases[arg2.Id] or nil
			if type(flag4) ~= "table" then
				return 0
			end
			local shopPeriod = type(snapshot) == "table" and snapshot.ShopPeriod or nil
			if flag4.Period ~= nil and shopPeriod ~= nil and flag4.Period ~= shopPeriod then
				return 0
			end
			return tonumber(flag4.Count) or 0
		end

		slicedfn31 = function(arg)
			local sliced9 = slicedfn9(true)
			if type(sliced9) ~= "table" or type(sliced9.Shop) ~= "table" then
				return
			end

			for _, sliced10 in ipairs(tbl11) do
				if arg() then
					return
				end

				if tbl18[sliced10.Label] == true then
					for i = 1, 10 do
						local sliced11 = snapshot
						local sliced12 = slicedfn10()
						local sliced13, sliced14, sliced15 = ipairs(type(sliced11) == "table" and sliced11.Shop or {})
						local sliced16 = nil

						for _, sliced17 in sliced13, sliced14, sliced15 do
							if type(sliced17) == "table" and sliced17.Id == sliced10.Id then
								sliced16 = sliced17
							end
						end

						if not (not sliced16 or not sliced12 or arg()) then
							local num = tonumber(sliced16.PurchaseLimit)

							if not (num and slicedfn30(sliced12, sliced16) >= num) then
								if not ((tonumber(sliced12.Samples) or 0) - (tonumber(sliced16.Price) or math.huge) < slicedn4) then
									local Shop = slicedfn8("Shop", sliced16.Id, { Quote = sliced16.Quote, Sequence = tonumber(sliced12.ShopSequence) or 0 })

									if not (type(Shop) ~= "table" or Shop.Ok ~= true) then
										str = "Bought " .. sliced10.Label
										task.wait(0.4)
										continue
									end
								end
							end
						end

						break
					end
				end
			end
		end
	end

	local slicedn10, slicedn11, slicedn12, tbl17, tbl18, sliced9, slicedn13, slicedn14, slicedfn32, sliced10
	local slicedfn33, slicedfn34, slicedfn35, slicedfn36

	do
		local slicedn15 = 98
		slicedn10 = 12
		slicedn11 = 20
		slicedn12 = 3

		tbl17 = {
			Vector3.new(2000, 90, -360),
			Vector3.new(2700, 90, -370),
			Vector3.new(3400, 90, -365),
			Vector3.new(4100, 90, -360),
			Vector3.new(4800, 90, -370),
			Vector3.new(5500, 90, -360),
			Vector3.new(5900, 90, -365),
		}

		tbl18 = {}
		local tbl19 = { Link = nil, Goal = nil, Look = nil, Character = nil }
		local userId = localPlayer.UserId
		local tbl20 = {}

		for _, sliced11 in ipairs({
			{ Label = "Scrap Drone", Tier = "ScrapDrone" },
			{ Label = "Reactor Drone", Tier = "ReactorDrone" },
			{ Label = "Augmented Drone", Tier = "AugmentedDrone" },
		}) do
			tbl20[#tbl20 + 1] = sliced11.Label
		end

		local tbl21 = { ScrapDrone = true, ReactorDrone = true, AugmentedDrone = true }
		local sliced11 = ({ "Nearest", "Rare First", "Most HP First" })[1]
		sliced9 = ({ "Tween", "Teleport" })[1]
		slicedn13 = 110
		slicedn14 = 1.5
		local slicedn16 = 0
		local slicedn17 = -math.huge

		local function slicedfn37(arg)
			local num = type(arg) == "table" and tonumber(arg.OwnerUserId) or nil
			return num == nil or num == userId
		end

		local function slicedfn38(arg)
			if typeof(arg) == "CFrame" then
				return arg.Position
			end

			if typeof(arg) == "Vector3" then
				return arg
			end
			return nil
		end

		local function slicedfn39(arg, arg2)
			local sliced12 = networking:FindFirstChild(arg)
			if not sliced12 or not sliced12:IsA("RemoteEvent") then
				return
			end

			local connection = sliced12.OnClientEvent:Connect(function(...)
				pcall(arg2, ...)
			end)

			slicedfn4(function()
				pcall(function()
					connection:Disconnect()
				end)
			end)
		end

		slicedfn39("RE/Scramble/Drones", function(arg)
			if type(arg) ~= "table" then
				return
			end
			local pairs = pairs
			local upserts = type(arg.Upserts) == "table" and arg.Upserts or {}

			for _, upsert in pairs(upserts) do
				if type(upsert) == "table" and upsert.Id ~= nil and slicedfn37(upsert) then
					local id = tostring(upsert.Id)
					local attributes = type(upsert.Attributes) == "table" and upsert.Attributes or {}
					local tbl22 = tbl12[id] or {}
					tbl22.Id = id
					tbl22.Position = slicedfn38(upsert.CFrame) or tbl22.Position
					tbl22.Health = tonumber(upsert.Health) or tbl22.Health or 1
					tbl22.Tier = tostring(attributes.ScrambleTier or tbl22.Tier or "")
					tbl22.Area = tostring(attributes.ScrambleArea or tbl22.Area or "")
					tbl22.Seen = os.clock()
					tbl12[id] = tbl22
				end
			end

			local sliced13 = pairs
			local removed = type(arg.Removed) == "table" and arg.Removed or {}

			for k, sliced14 in sliced13(removed) do
				tbl12[tostring(type(sliced14) == "string" and sliced14 or k)] = nil
			end
		end)

		slicedfn39("RE/Scramble/Effect", function(arg, arg2, arg3)
			if arg ~= "Hit" or type(arg3) ~= "table" or arg3.DroneId == nil then
				return
			end
			local sliced12 = tbl12[tostring(arg3.DroneId)]
			if not sliced12 then
				return
			end
			sliced12.Position = slicedfn38(arg2) or sliced12.Position
			sliced12.Health = (tonumber(sliced12.Health) or 1) - (tonumber(arg3.Amount) or 1)

			if type(arg3.Motion) == "string" and string.find(arg3.Motion, "\"Death\"", 1, true) then
				sliced12.Health = 0
			end

			if sliced12.Health <= 0 then
				tbl12[sliced12.Id] = nil
			end
		end)

		slicedfn39("RE/Scramble/Drops", function(arg)
			local pairs = pairs
			local tbl22 = type(arg) == "table" and arg or {}

			for _, sliced13 in pairs(tbl22) do
				if type(sliced13) == "table" and sliced13.Id ~= nil and slicedfn37(sliced13) then
					local sliced14 = slicedfn38(sliced13.Position) or slicedfn38(sliced13.Origin)

					if sliced14 then
						tbl13[tostring(sliced13.Id)] = {
							Position = sliced14,
							Radius = tonumber(sliced13.Radius) or 6,
							ExpiresAt = tonumber(sliced13.ExpiresAt),
							Kind = sliced13.Kind,
						}
					end
				end
			end
		end)

		slicedfn39("RE/Scramble/State", function(arg)
			if type(arg) ~= "table" then
				return
			end

			if arg.Patch == true and type(snapshot) == "table" then
				for k, sliced12 in pairs(arg) do
					if k ~= "Patch" then
						snapshot[k] = sliced12
					end
				end
			elseif type(arg.State) == "table" then
				snapshot = arg
			end

			slicedn5 = os.clock()
		end)

		slicedfn39("RE/Scramble/RemoveDrops", function(arg)
			local pairs = pairs
			local tbl22 = type(arg) == "table" and arg or {}

			for k, sliced13 in pairs(tbl22) do
				local sliced14 = tbl13
				local tostring = tostring
				sliced13 = type(sliced13) == "string" and sliced13 or k
				sliced14[tostring(sliced13)] = nil
			end
		end)

		local function slicedfn40(arg)
			local scrambleLocalVisuals = workspace:FindFirstChild("ScrambleLocalVisuals")
			return scrambleLocalVisuals and scrambleLocalVisuals:FindFirstChild("PersonalDrone_" .. arg) or nil
		end

		local sliced12 = nil
		local slicedn18 = 0

		local function slicedfn41()
			if sliced12 and next(sliced12) ~= nil then
				return sliced12
			end
			sliced12 = nil
			if os.clock() < slicedn18 or type(getgc) ~= "function" or not slicedfn12() then
				return nil
			end
			slicedn18 = os.clock() + 15

			for _, sliced13 in ipairs(getgc(false)) do
				if type(sliced13) == "function" and islclosure(sliced13) then
					local ok, result = pcall(debug.info, sliced13, "s")

					if ok and type(result) == "string" and string.find(result, "PersonalDrones", 1, true) then
						local ok2, result2 = pcall(debug.getupvalues, sliced13)

						if ok2 and type(result2) == "table" then
							for _, sliced14 in pairs(result2) do
								if type(sliced14) == "table" then
									local key, sliced15 = next(sliced14)
									if type(sliced15) == "table" and sliced15.OwnerUserId ~= nil and sliced15.CFrame ~= nil then
										sliced12 = sliced14
										return sliced14
									end
								end
							end

							continue
						end
					end
				end
			end

			return nil
		end

		local function slicedfn42()
			local sliced13 = slicedfn41()
			if not sliced13 then
				return
			end

			for k, sliced14 in pairs(sliced13) do
				if type(sliced14) == "table" and slicedfn37(sliced14) then
					local str3 = tostring(sliced14.Id or k)
					local attributes = type(sliced14.Attributes) == "table" and sliced14.Attributes or {}
					local tbl22 = tbl12[str3]
					local num = tonumber(sliced14.Health)

					if not tbl22 then
						tbl22 = { Id = str3, Health = num or 1 }
						tbl12[str3] = tbl22
					elseif num then
						tbl22.Health = math.min(num, tonumber(tbl22.Health) or num)
					end

					tbl22.Position = slicedfn38(sliced14.CFrame) or tbl22.Position
					tbl22.Tier = tostring(attributes.ScrambleTier or tbl22.Tier or "")
					tbl22.Area = tostring(attributes.ScrambleArea or tbl22.Area or "")

					if attributes.DroneState == "Death" then
						tbl22.Health = 0
					end
				end
			end

			for k in pairs(tbl12) do
				if sliced13[k] == nil then
					tbl12[k] = nil
				end
			end
		end

		local function slicedfn43()
			pcall(slicedfn42)
			local scrambleLocalVisuals = workspace:FindFirstChild("ScrambleLocalVisuals")
			if not scrambleLocalVisuals then
				return
			end

			for _, child in ipairs(scrambleLocalVisuals:GetChildren()) do
				local attribute = child:GetAttribute("ScrambleDroneId")

				if child:IsA("Model") and attribute ~= nil and string.sub(child.Name, 1, 14) == "PersonalDrone_" then
					local str3 = tostring(attribute)

					if child:GetAttribute("DroneState") == "Death" then
						tbl12[str3] = nil
					elseif not tbl12[str3] then
						local ok, result = pcall(child.GetPivot, child)

						tbl12[str3] = {
							Id = str3,
							Position = ok and result.Position or nil,
							Health = tonumber(child:GetAttribute("Health")) or 1,
							Tier = tostring(child:GetAttribute("ScrambleTier") or ""),
							Area = tostring(child:GetAttribute("ScrambleArea") or ""),
							Seen = os.clock(),
						}
					end
				end
			end
		end

		local function slicedfn44(arg)
			local sliced13 = slicedfn40(arg.Id)
			local hitbox = sliced13 and sliced13:FindFirstChild("Hitbox")
			if hitbox and hitbox:IsA("BasePart") then
				return hitbox.Position
			end

			if sliced13 and sliced13.PrimaryPart then
				return sliced13.PrimaryPart.Position
			end
			return arg.Position
		end

		local function slicedfn45()
			local tbl22 = {}
			local now = os.clock()

			for k, sliced13 in pairs(tbl12) do
				local flag4 = sliced13.Tier == nil or sliced13.Tier == "" or tbl21[sliced13.Tier] == true

				if flag4 then
					flag4 = (tonumber(sliced13.Health) or 0) > 0
				end

				flag4 = flag4 and sliced13.Position
				local flag5

				if flag4 then
					flag5 = (tbl18[k] or 0) <= now
				else
					flag5 = flag4
				end

				if flag5 then
					tbl22[#tbl22 + 1] = sliced13
				end
			end

			return tbl22
		end

		local function slicedfn46()
			local sliced13 = slicedfn16()
			if not sliced13 then
				return nil
			end
			local huge = math.huge
			local sliced14 = nil

			for _, sliced15 in ipairs(slicedfn45()) do
				local magnitude = ((slicedfn44(sliced15) or sliced15.Position) - sliced13.Position).Magnitude
				local sliced16 = sliced11
				local slicedn19

				if sliced16 == "Rare First" then
					if sliced15.Tier == "AugmentedDrone" then
						slicedn19 = magnitude - 200000
					elseif sliced15.Tier ~= "ReactorDrone" then
						slicedn19 = magnitude
					else
						slicedn19 = magnitude - 100000
					end
				elseif sliced16 == "Most HP First" then
					slicedn19 = magnitude - (tonumber(sliced15.Health) or 0) * 100000
				else
					slicedn19 = magnitude
				end

				if slicedn19 < huge then
					huge = slicedn19
					sliced14 = sliced15
				end
			end

			return sliced14
		end

		local function slicedfn47()
			local sliced13 = slicedfn16()
			if not sliced13 then
				return nil, nil
			end
			local serverTimeNow = workspace:GetServerTimeNow()
			local huge = math.huge
			local sliced14 = nil
			local sliced15 = nil

			for k, sliced16 in pairs(tbl13) do
				if sliced16.ExpiresAt and sliced16.ExpiresAt < serverTimeNow then
					tbl13[k] = nil
				else
					local magnitude = (sliced16.Position - sliced13.Position).Magnitude
					local slicedn19

					if sliced16.Kind == "Part" then
						slicedn19 = magnitude - 100000
					else
						slicedn19 = magnitude
					end

					if slicedn19 < huge then
						huge = slicedn19
						sliced14 = k
						sliced15 = sliced16
					end
				end
			end

			return sliced14, sliced15
		end

		slicedfn32 = function()
			if not tbl19.Link then
				if tbl19.SwapWait then
					tbl19.SwapWait = nil
					tbl4.Shield("scramble", false)
				end

				return
			end

			tbl19.Link:Disconnect()
			local sliced13 = tbl19
			local sliced14 = tbl19
			local sliced15 = tbl19
			tbl19.Link = nil
			sliced13.Goal = nil
			sliced14.Look = nil
			sliced15.Character = nil
			local sliced16 = tbl19
			local sliced17 = tbl19
			local sliced18 = tbl19
			local sliced19 = tbl19
			tbl19.Track = nil
			sliced16.Dir = nil
			sliced17.Last = nil
			sliced18.LastAt = nil
			sliced19.Vel = nil
			tbl4.Driving = math.max(0, tbl4.Driving - 1)
			tbl4.Shield("scramble", false)
		end

		slicedfn4(slicedfn32)

		local function slicedfn48(goal, look, track)
			if track ~= tbl19.Track then
				local sliced13 = tbl19
				local sliced14 = tbl19
				tbl19.Last = nil
				sliced13.LastAt = nil
				sliced14.Vel = nil
			end

			local sliced13 = tbl19
			local sliced14 = tbl19
			tbl19.Goal = goal
			sliced13.Look = look
			sliced14.Track = track
			local character = localPlayer.Character

			if tbl19.Link and tbl19.Character ~= character then
				slicedfn32()
				local sliced15 = tbl19
				local sliced16 = tbl19
				tbl19.Goal = goal
				sliced15.Look = look
				sliced16.Track = track
			end

			if tbl19.Link or not character then
				return
			end

			if not tbl4.Swapped() then
				tbl4.Shield("scramble", true)
				tbl19.SwapWait = tbl19.SwapWait or os.clock() + 6
				local swapWait = tbl19.SwapWait
				if os.clock() < swapWait then
					str = "Waiting for the character to settle"
					return
				end
			end

			if tbl19.SwapWait then
				tbl19.SwapWait = nil
			else
				tbl4.Shield("scramble", true)
			end

			tbl19.Character = character
			tbl4.Driving = tbl4.Driving + 1

			tbl19.Link = RunService.Heartbeat:Connect(function(deltaTime)
				local sliced15 = tbl4.Root()
				local goal2 = tbl19.Goal
				if not sliced15 or not goal2 or sliced15.Parent ~= tbl19.Character or tbl4.AntiGuard.Busy or tbl4.Movement.Owner ~= "scramble" then
					return
				end
				local position = sliced15.Position

				if tbl19.Track then
					local ok, last = pcall(tbl19.Track)

					if ok and typeof(last) == "Vector3" then
						local now = os.clock()

						if not tbl19.Last or not tbl19.LastAt then
							local sliced16 = tbl19
							tbl19.Last = last
							sliced16.LastAt = now
						elseif (last - tbl19.Last).Magnitude > 0.01 then
							local slicedn19 = math.max(now - tbl19.LastAt, 0.0041666666666666666)
							local slicedn20 = (last - tbl19.Last) / slicedn19

							if slicedn20.Magnitude < 400 then
								local slicedn21 = math.clamp(slicedn19 * 12, 0.2, 0.8)
								tbl19.Vel = tbl19.Vel and tbl19.Vel:Lerp(slicedn20, slicedn21) or slicedn20
							end

							local sliced16 = tbl19
							tbl19.Last = last
							sliced16.LastAt = now
						elseif now - tbl19.LastAt > 0.25 and tbl19.Vel then
							tbl19.Vel = tbl19.Vel:Lerp(Vector3.zero, math.clamp(deltaTime * 6, 0, 1))
						end

						local vel = tbl19.Vel or Vector3.zero
						local look2 = tbl19.Last + vel * (math.clamp(now - tbl19.LastAt, 0, 0.25) + 0.1)
						local vector = Vector3.new(position.X - look2.X, 0, position.Z - look2.Z)

						if vector.Magnitude > 0.5 then
							local unit = vector.Unit
							local slicedn19 = math.clamp(deltaTime * 5, 0, 1)
							local dir = tbl19.Dir and tbl19.Dir:Lerp(unit, slicedn19) or unit
							tbl19.Dir = dir.Magnitude > 0.01 and dir.Unit or unit
						end

						goal2 = look2 + (tbl19.Dir or Vector3.new(0, 0, 1)) * slicedn8 + Vector3.new(0, -1, 0)
						local sliced16 = tbl19
						tbl19.Goal = goal2
						sliced16.Look = look2

						if (goal2 - position).Magnitude <= 40 then
							local slicedn19 = math.max(deltaTime, 0.0041666666666666666)
							local slicedn20 = vel + (goal2 - position) / math.max(0.1, slicedn19)
							local slicedn21 = math.max(400, vel.Magnitude + 80)

							if slicedn21 < slicedn20.Magnitude then
								slicedn20 = slicedn20.Unit * slicedn21
							end

							local assemblyLinearVelocity = slicedn20 + Vector3.new(0, workspace.Gravity * slicedn19 * 0.5, 0)
							local vector2 = Vector3.new(look2.X - position.X, 0, look2.Z - position.Z)

							pcall(function()
								if vector2.Magnitude > 0.05 then
									sliced15.CFrame = CFrame.lookAt(position, position + vector2.Unit)
								end

								sliced15.AssemblyLinearVelocity = assemblyLinearVelocity
								sliced15.AssemblyAngularVelocity = Vector3.zero
							end)

							return
						end
					end
				end

				local vector

				if Vector3.new(goal2.X - position.X, 0, goal2.Z - position.Z).Magnitude > 250 then
					local slicedn19 = math.max(slicedn15, goal2.Y)
					vector = position.Y < slicedn19 - 2 and Vector3.new(position.X, slicedn19, position.Z) or Vector3.new(goal2.X, slicedn19, goal2.Z)
				else
					vector = goal2
				end

				local slicedn19 = vector - position
				local slicedn20 = slicedn3 * deltaTime
				vector = slicedn19.Magnitude <= slicedn20 and vector or position + slicedn19.Unit * slicedn20
				local look2 = tbl19.Look or goal2
				local vector2 = Vector3.new(look2.X - vector.X, 0, look2.Z - vector.Z)
				local cframe = vector2.Magnitude > 0.05 and CFrame.lookAt(Vector3.zero, vector2.Unit) or sliced15.CFrame.Rotation

				pcall(function()
					sliced15.CFrame = CFrame.new(vector) * cframe
					sliced15.AssemblyLinearVelocity = Vector3.zero
					sliced15.AssemblyAngularVelocity = Vector3.zero
				end)
			end)
		end

		local function slicedfn49(arg)
			if typeof(arg) ~= "Instance" or not arg:IsA("Tool") then
				return false
			end
			local attribute = arg:GetAttribute("GearName")
			local gears = tbl.Gears
			local directory = type(gears) == "table" and gears.Directory or nil
			local flag4 = type(attribute) == "string" and type(directory) == "table" and directory[attribute] or nil
			return type(flag4) == "table" and (flag4.ToolController == "Slap" or flag4.SlapPower ~= nil)
		end

		local function slicedfn50(arg)
			if typeof(arg) ~= "Instance" or not arg:IsA("Tool") then
				return false
			end

			if tostring(arg:GetAttribute("ItemType")) ~= "Gear" then
				return false
			end
			local str3 = tostring(arg:GetAttribute("GearName") or "")
			if str3 == "" then
				return false
			end
			return string.find(string.lower(str3), "scrambler", 1, true) ~= nil
		end

		local function slicedfn51()
			return localPlayer.Character, localPlayer:FindFirstChildOfClass("Backpack")
		end

		local function slicedfn52()
			local sliced13 = tbl4.FindBat()
			if sliced13 then
				return sliced13
			end
			local sliced14, sliced15 = slicedfn51()

			for _, sliced16 in ipairs({ sliced14, sliced15 }) do
				if sliced16 then
					for _, child in ipairs(sliced16:GetChildren()) do
						if slicedfn49(child) or slicedfn50(child) then
							return child
						end
					end
				end
			end

			return nil
		end

		tbl14.Valid = function(arg)
			if typeof(arg) ~= "Instance" or not arg:IsA("Tool") then
				return false
			end
			return tbl4.IsBatTool(arg) or slicedfn49(arg) or slicedfn50(arg)
		end

		tbl14.Owned = function(arg)
			if typeof(arg) ~= "Instance" or not arg:IsA("Tool") then
				return false
			end
			local sliced13, sliced14 = slicedfn51()
			local parent = arg.Parent
			local flag4 = parent ~= nil
			local flag5

			if flag4 then
				flag5 = parent == sliced13 or parent == sliced14
			else
				flag5 = flag4
			end

			return flag5
		end

		tbl14.Name = function(arg)
			if slicedfn50(arg) then
				return "The Scrambler"
			end
			return tostring(arg:GetAttribute("GearName") or arg.Name)
		end

		tbl14.Put = function(arg, arg2, parent)
			local equipAt = tbl14.EquipAt
			if os.clock() - equipAt < 0.4 then
				return false
			end
			tbl14.EquipAt = os.clock()

			pcall(function()
				arg2:EquipTool(arg)
			end)

			if arg.Parent ~= parent then
				pcall(function()
					arg.Parent = parent
				end)
			end

			return arg.Parent == parent
		end

		local function slicedfn53()
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildWhichIsA("Humanoid")
			if not character or not humanoid or humanoid.Health <= 0 then
				return nil, false
			end
			local tool = character:FindFirstChildWhichIsA("Tool")

			if tool ~= nil and tbl14.Valid(tool) then
				tbl14.Tool = tool
				str2 = tbl14.Name(tool)
				return tool, true
			end

			if not tbl14.Owned(tbl14.Tool) then
				tbl14.Tool = slicedfn52()
			end

			local tool2 = tbl14.Tool
			if not tool2 then
				str2 = ""
				return nil, false
			end
			str2 = tbl14.Name(tool2)
			tbl14.Put(tool2, humanoid, character)
			return tool2, tool2.Parent == character
		end

		local function slicedfn54()
			local sliced13, sliced14 = slicedfn53()

			if sliced13 and sliced14 then
				if flag2 then
					pcall(function()
						sliced13:Activate()
					end)

					task.defer(function()
						pcall(function()
							sliced13:Deactivate()
						end)
					end)
				else
					pcall(function()
						sliced13:Deactivate()
						sliced13:Activate()
					end)
				end
			end

			return sliced13 ~= nil
		end

		local function slicedfn55()
			local sliced13, sliced14 = slicedfn51()
			local sliced15 = nil
			local sliced16 = nil
			local sliced17 = nil

			for _, sliced18 in ipairs({ sliced13, sliced14 }) do
				if sliced18 then
					for _, child in ipairs(sliced18:GetChildren()) do
						if tbl14.Valid(child) then
							if slicedfn50(child) then
								sliced15 = sliced15 or child
							elseif tbl4.IsBatTool(child) and (sliced16 == nil or not tbl4.IsBatTool(sliced16)) then
								if sliced17 then
									sliced16 = child
								else
									sliced17 = sliced16
									sliced16 = child
								end
							elseif sliced16 == nil then
								sliced16 = child
							elseif sliced17 == nil then
								sliced17 = child
							end
						end
					end
				end
			end

			return sliced16, sliced15 or sliced17
		end

		local function slicedfn56(arg)
			pcall(function()
				arg:Activate()
			end)

			task.defer(function()
				pcall(function()
					arg:Deactivate()
				end)
			end)
		end

		tbl15.SpamUntil = 0
		tbl15.List = {}
		tbl15.Dirty = true
		tbl15.BuiltAt = 0
		tbl15.NextBag = 0
		tbl15.Links = {}

		tbl15.Click = function(arg)
			pcall(arg.Deactivate, arg)
			pcall(arg.Activate, arg)
		end

		tbl15.Rebuild = function()
			tbl15.Dirty = false
			tbl15.BuiltAt = os.clock()
			table.clear(tbl15.List)
			local sliced13, sliced14 = slicedfn51()

			for _, sliced15 in ipairs({ sliced13, sliced14 }) do
				if sliced15 then
					for _, child in ipairs(sliced15:GetChildren()) do
						if tbl14.Valid(child) then
							tbl15.List[#tbl15.List + 1] = child
						end
					end
				end
			end
		end

		tbl15.Beat = RunService.Heartbeat:Connect(function()
			local now = os.clock()
			if tbl15.SpamUntil <= now then
				return
			end

			if tbl15.Dirty or now - tbl15.BuiltAt > 1 then
				tbl15.Rebuild()
			end

			local character = localPlayer.Character
			local flag4 = now >= tbl15.NextBag

			if flag4 then
				tbl15.NextBag = now + 0.25
			end

			for _, sliced13 in ipairs(tbl15.List) do
				local parent = sliced13.Parent

				if parent == character then
					tbl15.Click(sliced13)
				elseif flag4 and parent ~= nil then
					tbl15.Click(sliced13)
				end
			end
		end)

		tbl15.Unwatch = function()
			for i = #tbl15.Links, 1, -1 do
				pcall(function()
					tbl15.Links[i]:Disconnect()
				end)

				tbl15.Links[i] = nil
			end
		end

		tbl15.Watch = function(arg)
			tbl15.Unwatch()
			tbl15.Dirty = true
			if not arg then
				return
			end

			tbl15.Links[#tbl15.Links + 1] = arg.ChildAdded:Connect(function(child)
				if not child:IsA("Tool") then
					return
				end
				tbl15.Dirty = true
				local spamUntil = tbl15.SpamUntil

				if os.clock() < spamUntil and tbl14.Valid(child) then
					tbl15.Click(child)
					task.defer(tbl15.Click, child)
				end
			end)

			tbl15.Links[#tbl15.Links + 1] = arg.ChildRemoved:Connect(function(child)
				if child:IsA("Tool") then
					tbl15.Dirty = true
				end
			end)

			task.defer(function()
				local backpack = localPlayer:FindFirstChildOfClass("Backpack") or localPlayer:WaitForChild("Backpack", 5)

				if backpack and localPlayer.Character == arg then
					tbl15.Links[#tbl15.Links + 1] = backpack.ChildAdded:Connect(function()
						tbl15.Dirty = true
					end)

					tbl15.Links[#tbl15.Links + 1] = backpack.ChildRemoved:Connect(function()
						tbl15.Dirty = true
					end)
				end
			end)
		end

		tbl15.Watch(localPlayer.Character)
		tbl15.CharLink = localPlayer.CharacterAdded:Connect(tbl15.Watch)

		slicedfn4(function()
			tbl15.SpamUntil = 0
			tbl15.Unwatch()

			for _, sliced13 in ipairs({ "Beat", "CharLink" }) do
				if tbl15[sliced13] then
					pcall(function()
						tbl15[sliced13]:Disconnect()
					end)

					tbl15[sliced13] = nil
				end
			end
		end)

		local function slicedfn57()
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildWhichIsA("Humanoid")
			if not character or not humanoid or humanoid.Health <= 0 then
				return false
			end
			local sliced13, sliced14 = slicedfn55()
			if not sliced13 or not sliced14 then
				return slicedfn54()
			end
			local tbl22 = { sliced13, sliced14 }
			local tbl23 = { 0.3, 0.4 }
			local sliced15 = tbl22[tbl15.Index]

			if tbl15.Tool ~= sliced15 then
				local sliced16 = tbl15
				local sliced17 = tbl15
				local now = os.clock()
				sliced16.Tool = sliced15
				sliced17.Since = now
			end

			local flag4 = sliced15.Parent == character

			if flag4 then
				local since = tbl15.Since
				flag4 = os.clock() - since >= tbl23[tbl15.Index]
			end

			if flag4 then
				tbl15.Index = tbl15.Index == 1 and 2 or 1
				sliced15 = tbl22[tbl15.Index]
				local sliced16 = tbl15
				local sliced17 = tbl15
				local now = os.clock()
				sliced16.Tool = sliced15
				sliced17.Since = now
			end

			tbl14.Tool = sliced15
			str2 = tbl14.Name(sliced15)

			if sliced15.Parent ~= character then
				pcall(function()
					humanoid:EquipTool(sliced15)
				end)

				if sliced15.Parent ~= character then
					pcall(function()
						sliced15.Parent = character
					end)
				end

				tbl15.Since = os.clock()

				if sliced15.Parent == character then
					slicedfn56(sliced15)
					task.defer(slicedfn56, sliced15)
				end

				return true
			end

			slicedfn56(sliced15)
			return true
		end

		local function slicedfn58(arg, arg2, arg3)
			local now = os.clock()
			local slicedn19 = now + slicedn12

			while os.clock() < slicedn19 and not arg() do
				local sliced13, sliced14 = slicedfn47()
				local flag4 = not sliced14

				if not flag4 then
					if arg2 then
						flag4 = (sliced14.Position - arg2).Magnitude > (arg3 or 40)
					else
						flag4 = arg2
					end
				end

				if flag4 then
					if arg2 and os.clock() - now < 1.2 then
						task.wait(0.1)
						continue
					end
					return
				end

				if slicedfn22() and not slicedfn22(sliced14.Position) then
					slicedfn32()
					str = "Leaving the base through the safe zone"
					if not slicedfn24(sliced14.Position + Vector3.new(0, 2.5, 0), arg, 6) then
						return
					end
					continue
				end

				str = sliced14.Kind == "Part" and "Picking up a Drone Part" or "Picking up Samples"
				slicedfn48(sliced14.Position + Vector3.new(0, 2.5, 0), sliced14.Position)
				local slicedn20 = os.clock() + 2.5

				while tbl13[sliced13] and os.clock() < slicedn20 and not arg() do
					task.wait(0.1)
				end

				tbl13[sliced13] = nil
				slicedn19 = os.clock() + 1.2
			end
		end

		local function slicedfn59(arg, arg2)
			local now = os.clock()
			local slicedn19 = tonumber(arg.Health) or 0
			local sliced13 = nil
			local sliced14 = nil
			local slicedfn60 = nil
			local flag4 = false

			while not arg2() do
				local sliced15 = tbl12[arg.Id]
				local flag5 = not sliced15

				if not flag5 then
					flag5 = (tonumber(sliced15.Health) or 0) <= 0
				end

				if flag5 then
					return true
				end
				local sliced16 = slicedfn40(arg.Id)
				if sliced16 and sliced16:GetAttribute("DroneState") == "Death" then
					tbl12[arg.Id] = nil
					return true
				end
				local sliced17 = slicedfn16()
				local flag6 = sliced17 ~= nil and sliced15.Position ~= nil

				if flag6 then
					flag6 = (sliced17.Position - (slicedfn44(sliced15) or sliced15.Position)).Magnitude <= 30
				end

				if flag6 and not sliced16 then
					local now2 = sliced13 or os.clock()
					if os.clock() - now2 > 1.5 then
						tbl12[arg.Id] = nil
						return false
					end
					sliced13 = now2
				else
					sliced13 = nil
				end

				local slicedn20 = tonumber(sliced15.Health) or 0

				if slicedn20 ~= slicedn19 then
					sliced14 = nil
					slicedn19 = slicedn20
				end

				if slicedn11 < os.clock() - now then
					tbl18[arg.Id] = os.clock() + 30
					return false
				end
				local position = slicedfn44(sliced15) or sliced15.Position
				local sliced18 = slicedfn16()
				if not sliced18 then
					return false
				end

				if slicedfn22() and not slicedfn22(position) then
					slicedfn32()
					str = "Leaving the base through the safe zone"
					if not slicedfn24(position, arg2, 12) then
						return false
					end

					if arg2() then
						return false
					end
				end

				if not slicedfn60 then
					local sliced19 = nil
					local isBasePart = nil

					slicedfn60 = function()
						local sliced20 = tbl12[arg.Id]
						if not sliced20 then
							return nil
						end

						if not sliced19 or not sliced19.Parent then
							sliced19 = slicedfn40(arg.Id)
							local hitbox = sliced19 and sliced19:FindFirstChild("Hitbox")
							isBasePart = hitbox and hitbox:IsA("BasePart") and hitbox or sliced19 and sliced19.PrimaryPart or nil
						end

						if isBasePart and isBasePart.Parent then
							return isBasePart.Position
						end
						return sliced20.Position
					end
				end

				if flag2 then
					slicedfn48(position + Vector3.new(0, -1, 16), position, slicedfn60)
				else
					slicedfn48(position + Vector3.new(0, -1, 5), position)
				end

				if (sliced18.Position - position).Magnitude <= 60 and not flag2 then
					slicedfn53()
				end

				local magnitude = (sliced18.Position - position).Magnitude
				local flag7 = false

				if flag2 then
					flag7 = math.max(12, slicedn8 + 7)
				end

				local flag8 = magnitude <= (flag7 or 12)

				if flag8 then
					if flag2 then
						tbl15.SpamUntil = os.clock() + 0.2
					end

					local now2 = sliced14 or os.clock()
					if os.clock() - now2 > 8 then
						tbl18[arg.Id] = os.clock() + 30
						return false
					end
					local flag9 = false

					if flag2 then
						flag9 = slicedfn57()
					end

					if flag9 or not flag2 and slicedfn54() then
						str = string.format("Smashing %s  %d HP", sliced15.Tier ~= "" and sliced15.Tier or "drone", math.max(0, tonumber(sliced15.Health) or 0))
						sliced14 = now2
					elseif not flag4 then
						str = "No bat found, get any bat to smash drones"
						flag4 = true
						sliced14 = now2
					else
						sliced14 = now2
					end
				else
					str = "Flying to a drone"
				end

				local wait = task.wait
				local flag9 = false

				if flag2 then
					flag9 = flag8
				end

				wait(flag9 and 0.03 or 0.1)
			end

			return false
		end

		local function slicedfn60(arg)
			for _, sliced13 in ipairs(tbl17) do
				if arg() then
					return false
				end
				str = "Looking for drones"
				slicedfn48(sliced13)
				local slicedn19 = os.clock() + 12

				while os.clock() < slicedn19 and not arg() do
					slicedfn43()
					if #slicedfn45() > 0 then
						return true
					end

					if tbl4.DistanceTo(sliced13) < 8 then
						break
					end
					task.wait(0.2)
				end
			end

			return #slicedfn45() > 0
		end

		local function slicedfn61()
			local serverTimeNow = workspace:GetServerTimeNow()
			local sliced13, sliced14 = slicedfn12()
			if sliced13 and sliced14 and sliced14 < 25 then
				return next(tbl13) ~= nil
			end

			for _, sliced15 in pairs(tbl13) do
				if sliced15.Kind == "Part" or sliced15.ExpiresAt and sliced15.ExpiresAt - serverTimeNow < 30 then
					return true
				end
			end

			return false
		end

		local sliced13 = nil

		local function slicedfn62()
			local window = type(snapshot) == "table" and snapshot.Window or nil
			return type(window) == "table" and window.Index or nil
		end

		local function slicedfn63(arg)
			local flag4 = sliced13 ~= nil and sliced13 == slicedfn62()

			while not arg() do
				RunService.Heartbeat:Wait()
				if arg() then
					break
				end
				slicedfn43()

				if slicedfn61() then
					slicedfn58(arg)
				end

				if slicedfn22() then
					slicedfn32()
					if not slicedfn23(arg) then
						break
					end
				end

				local sliced14 = slicedfn46()

				if not sliced14 and next(tbl13) ~= nil then
					slicedfn58(arg)
					slicedfn43()
					sliced14 = slicedfn46()
				end

				if not sliced14 then
					if not slicedfn12() or flag4 then
						break
					end
					sliced13 = slicedfn62()
					local flag5 = true
					flag4 = true
					if not slicedfn60(arg) then
						break
					end
					continue
				end

				local position = slicedfn44(sliced14) or sliced14.Position
				local flag5 = slicedfn16()
				local magnitude = flag5 and (flag5.Position - position).Magnitude or 0
				flag5 = sliced9 == "Teleport" and flag5

				if flag5 then
					flag5 = not (slicedfn22() and not slicedfn22(position))
				end

				if flag5 then
					if magnitude > slicedn10 and magnitude <= slicedn13 and os.clock() >= slicedn16 and os.clock() - slicedn17 >= slicedn14 then
						slicedn17 = os.clock()
						local vector = Vector3.new
						local flag6 = false

						if flag2 then
							flag6 = 16
						end

						local slicedn19 = position + vector(0, -1, flag6 or 5)
						slicedfn48(slicedn19, position)
						local sliced15 = slicedfn16()

						if sliced15 then
							str = "Teleporting to the next drone"

							pcall(function()
								sliced15.CFrame = CFrame.lookAt(slicedn19, Vector3.new(position.X, slicedn19.Y, position.Z))
								sliced15.AssemblyLinearVelocity = Vector3.zero
								sliced15.AssemblyAngularVelocity = Vector3.zero
							end)

							local slicedn20 = os.clock() + 0.8

							while true do
								if os.clock() < slicedn20 and not arg() then
									local sliced16 = slicedfn16()

									if sliced16 and (sliced16.Position - slicedn19).Magnitude > 40 then
										slicedn16 = os.clock() + 30
										str = "Teleport pulled back, tweening"
										break
									else
										RunService.Heartbeat:Wait()
										continue
									end
								end

								break
							end
						end
					end
				end

				slicedfn59(sliced14, arg)
			end

			slicedfn58(arg)
			slicedfn32()
		end

		local tbl22 = { LostPart1 = "Mechanical Gear", LostPart2 = "Wiring Harness" }

		tbl4.ScrambleLostPart = function(arg)
			return slicedfn13(slicedfn10(), arg)
		end

		sliced10 = nil

		slicedfn33 = function()
			local sliced14 = slicedfn10()
			if not sliced14 then
				return "Lost Parts: no event data"
			end
			local drScrambleEvent = workspace:FindFirstChild("DrScrambleEvent")
			local tbl23 = {}
			local slicedn19 = 0
			local slicedn20 = 0

			for _, sliced15 in ipairs(tbl10) do
				local sliced16 = drScrambleEvent and drScrambleEvent:FindFirstChild(sliced15)

				if sliced16 then
					slicedn19 += 1
				end

				if slicedfn13(sliced14, sliced15) then
					slicedn20 += 1
				elseif sliced16 then
					local ok, result = pcall(sliced16.GetPivot, sliced16)
					ok = ok and tbl4.DistanceTo(result.Position) or nil
					tbl23[#tbl23 + 1] = ok and string.format("%s %d studs", tbl22[sliced15], math.floor(ok)) or tbl22[sliced15]
				else
					tbl23[#tbl23 + 1] = tbl22[sliced15] .. " not on map"
				end
			end

			local str3 = string.format("Lost Parts on map %d/2  -  Collected %d/2", slicedn19, slicedn20)
			local str4

			if #tbl23 > 0 then
				str4 = str3 .. "  -  " .. table.concat(tbl23, "  -  ")
			else
				str4 = str3
			end

			return str4
		end

		local function slicedfn64(arg)
			if not slicedfn21() then
				return true
			end
			local Exit = slicedfn19("Exit")
			local sliced14 = slicedfn20(Exit, nil)
			if not sliced14 then
				return false
			end
			str = "Leaving the Secret Cave"
			if not slicedfn17(sliced14, arg, 4) then
				return false
			end

			for i = 1, 4 do
				if arg() then
					return false
				end
				slicedfn18(Exit or slicedfn19("Exit"))
				local slicedn19 = os.clock() + 1.5

				while os.clock() < slicedn19 and slicedfn21() do
					RunService.Heartbeat:Wait()
				end

				if not slicedfn21() then
					return true
				end
			end

			return not slicedfn21()
		end

		local function slicedfn65()
			return tbl4.IsNight() or tbl4.WallSealed()
		end

		local function slicedfn66(arg)
			if not slicedfn65() then
				return true
			end
			slicedfn32()

			while slicedfn65() and not arg() do
				str = tbl4.IsNight() and "Night, waiting for the wall to drop" or "Waiting for the wall to drop"
				RunService.Heartbeat:Wait()
			end

			return not arg()
		end

		slicedfn34 = function()
			if not tbl4.Toggle(nil, false) or not slicedfn11() then
				return false
			end

			if tbl16.Ended then
				return false
			end

			if slicedfn12() then
				return true
			end
			slicedfn43()
			return #slicedfn45() > 0 or next(tbl13) ~= nil
		end

		slicedfn35 = function()
			local sliced14 = slicedfn10()
			if not sliced14 or sliced14.Completed == true or not slicedfn11() then
				return false
			end
			local num = tonumber(sliced14.TotalParts)

			if not num then
				num = slicedfn14(sliced14) + (tonumber(sliced14.DroneParts) or 0)
			end

			local flag4 = tbl4.Toggle(nil, false)

			if flag4 then
				local slicedn19 = #tbl10
				flag4 = slicedfn14(sliced14) < slicedn19
			end

			local flag5 = tbl4.Toggle(nil, false) and (num >= 5 or sliced14.Discovered ~= true)
			return flag4 or flag5
		end

		slicedfn36 = function(arg)
			local function slicedfn67()
				return arg ~= slicedn6 or tbl4.Movement.Owner ~= "scramble"
			end

			local function slicedfn68()
				return slicedfn67() or not slicedfn34() or slicedfn65()
			end

			while true do
				if slicedfn34() and not slicedfn67() then
					if slicedfn66(slicedfn67) then
						pcall(slicedfn63, slicedfn68)
						if slicedfn65() then
							continue
						end
					end
				end

				break
			end

			slicedfn32()
			if slicedfn67() or slicedfn34() then
				return
			end

			if not slicedfn35() then
				slicedfn25(slicedfn67)
				str = ""
				return
			end

			if not slicedfn66(slicedfn67) then
				return
			end
			slicedfn9(true)
			local sliced14 = slicedfn10()
			if not sliced14 then
				return
			end

			if not slicedfn35() then
				str = ""
				return
			end

			if tbl4.Toggle(nil, false) and sliced14.Discovered ~= true then
				pcall(slicedfn26, slicedfn67)
			end

			if tbl4.Toggle(nil, false) then
				pcall(slicedfn27, function()
					return slicedfn67() or not tbl4.Toggle(nil, false) or slicedfn34() or slicedfn65()
				end)
			end

			if tbl4.Toggle(nil, false) then
				pcall(slicedfn28, function()
					return slicedfn67() or not tbl4.Toggle(nil, false) or slicedfn34() or slicedfn65()
				end)
			end

			if slicedfn21() and not slicedfn67() then
				pcall(slicedfn64, slicedfn67)
			end

			if not slicedfn21() and not slicedfn34() then
				pcall(slicedfn25, slicedfn67)
			end
		end
	end

	local slicedfn37

	slicedfn37 = function(arg)
		if not (tbl4.Treadmill.Riding or tbl4.OnBelt()) then
			return true
		end

		for i = 1, 3 do
			if arg() then
				return false
			end
			str = "Jumping off the treadmill"
			tbl4.Treadmill.Riding = false
			task.spawn(tbl4.LeaveBelt)
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")

			if humanoid then
				pcall(function()
					humanoid.Sit = false
					humanoid.Jump = true
					humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
				end)
			end

			local sliced11 = slicedfn16()

			if sliced11 then
				local position = sliced11.Position
				local slicedn15 = position + Vector3.new(0, 18, 0)
				local now = os.clock()

				while true do
					RunService.Heartbeat:Wait()
					local sliced12 = slicedfn16()

					if not sliced12 then
						break
					else
						local slicedn16 = math.min(1, (os.clock() - now) / 0.25)

						pcall(function()
							local rotation = sliced12.CFrame.Rotation
							sliced12.CFrame = CFrame.new(position:Lerp(slicedn15, slicedn16)) * rotation
							sliced12.AssemblyLinearVelocity = Vector3.zero
							sliced12.AssemblyAngularVelocity = Vector3.zero
						end)

						if not (slicedn16 >= 1) then
							continue
						end
						break
					end
				end
			end

			if not (tbl4.Treadmill.Riding or tbl4.OnBelt()) then
				return true
			end
		end

		return not tbl4.OnBelt()
	end

	do
		local tbl19 = { "Highest Value", "Best Rarity", "Biggest Size" }
		local tbl20 = { idle = "#8C93A6", work = "#FFC857", good = "#57E08A", stop = "#FF6B6B" }
		local slicedn15 = 6

		local tbl21 = {
			Handle = nil,
			BuyHandle = nil,
			Loop = 0,
			MinRarity = 0,
			MinIncome = 0,
			Priority = tbl19[1],
			SkipMutated = true,
			Targets = {},
			Cooldown = 0,
			Status = "Idle",
			State = "idle",
			Detail = "Turn it on to start applying Scrambled",
			RarityColor = "#FFFFFF",
			Icon = "",
			Ui = {},
			Row = nil,
			Left = 0,
			Pen = 0,
			Match = 0,
			Tries = 0,
			Hits = 0,
			Locked = nil,
			Short = false,
			EggOptions = {},
			EggCategory = {},
		}

		local directory = tbl.Assets and tbl.Assets.Directory
		local tbl22 = {}

		if type(directory) == "table" then
			for k, sliced11 in pairs(directory) do
				local rarity = type(sliced11) == "table" and sliced11.Rarity or nil
				local flag4 = type(rarity) == "table"

				if flag4 then
					flag4 = tonumber(rarity.RarityNumber or rarity.Rank)
				end

				local sliced12 = flag4 or nil

				if sliced12 then
					table.insert(tbl22, {
						Category = tostring(k),
						Name = tostring(sliced11.DisplayName or k),
						Rarity = sliced12,
						RarityName = tostring(rarity.DisplayName or rarity._id or sliced12),
					})
				end
			end
		end

		table.sort(tbl22, function(arg, arg2)
			if arg.Rarity ~= arg2.Rarity then
				return arg.Rarity > arg2.Rarity
			end
			return arg.Name < arg2.Name
		end)

		for _, sliced11 in ipairs(tbl22) do
			local str3 = string.format("%s [%s]", sliced11.Name, sliced11.RarityName)

			if tbl21.EggCategory[str3] then
				str3 = string.format("%s [%s] (%s)", sliced11.Name, sliced11.RarityName, sliced11.Category)
			end

			table.insert(tbl21.EggOptions, str3)
			tbl21.EggCategory[str3] = sliced11.Category
		end

		local function slicedfn38(arg)
			local directory2 = tbl.Assets and tbl.Assets.Directory
			return type(directory2) == "table" and directory2[tostring(arg)] or nil
		end

		local function slicedfn39(arg)
			local sliced11 = slicedfn38(arg.AssetCategory)
			local rarity = type(sliced11) == "table" and sliced11.Rarity or nil
			local flag4 = type(rarity) == "table"

			if flag4 then
				flag4 = tonumber(rarity.RarityNumber or rarity.Rank)
			end

			return flag4 or 0
		end

		local function slicedfn40(arg)
			local sliced11 = slicedfn38(arg.AssetCategory)
			local slicedn16 = type(sliced11) == "table" and tonumber(sliced11.EarningRate) or 0
			local slicedn17 = tonumber(arg.AssetScale) or 0
			if slicedn16 <= 0 or slicedn17 <= 0 then
				return 0
			end
			return slicedn16 * (slicedn17 > 5 and (slicedn17 / 5) ^ 1.2 * 19.637875755794113 or slicedn17 ^ 1.85)
		end

		local function slicedfn41(arg)
			if tostring(arg.BaseMutation or "") == "Scrambled" then
				return true
			end

			if type(arg.Mutations) == "table" then
				for k, mutation in pairs(arg.Mutations) do
					if type(mutation) == "string" and mutation == "Scrambled" then
						return true
					end

					if type(k) == "string" and k == "Scrambled" and mutation ~= false then
						return true
					end
				end
			end

			return false
		end

		local function slicedfn42()
			local eggState = tbl.EggState
			if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
				return {}
			end
			local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
			if not ok or type(result) ~= "table" then
				return {}
			end
			local tbl23 = {}

			for k, sliced11 in pairs(result) do
				if type(sliced11) == "table" and sliced11.Placement ~= nil then
					k = sliced11.Uid or k
					sliced11.Uid = k
					tbl23[#tbl23 + 1] = sliced11
				end
			end

			return tbl23
		end

		local function slicedfn43(arg)
			arg = arg and arg.Uid

			if arg then
				local areaEggSlotsClient = workspace:FindFirstChild("AreaEggSlotsClient")
				areaEggSlotsClient = areaEggSlotsClient and areaEggSlotsClient:FindFirstChild(arg)

				if areaEggSlotsClient then
					local ok, result = pcall(function()
						return areaEggSlotsClient:GetPivot().Position
					end)

					if ok and typeof(result) == "Vector3" then
						return result
					end
				end
			end

			if type(tbl4.PenAnchor) == "function" then
				local ok, result = pcall(tbl4.PenAnchor)
				if ok and typeof(result) == "Vector3" then
					return result
				end
			end

			return nil
		end

		local function slicedfn44(arg, arg2)
			local sliced11 = slicedfn43(arg)
			if sliced11 == nil then
				return true
			end

			if tbl4.DistanceTo(sliced11) <= slicedn15 then
				return true
			end

			local function slicedfn45()
				if arg2 ~= tbl21.Loop or not tbl4.Toggle(tbl21.Handle, false) then
					return true
				end

				if tbl4.Movement.PlaceWanted == true then
					return true
				end
				return tbl4.Movement.ScrambleWanted == true or tbl4.Steal.Wanted == true
			end

			if tbl4.Treadmill.Riding or tbl4.OnBelt() then
				tbl4.ExitBelt()
			end

			tbl4.HoldBelt()
			local ok, result = pcall(tbl4.FlyTo, sliced11 + Vector3.new(0, 3, 0), slicedfn45, "mutation")
			tbl4.ReleaseBelt()
			tbl4.LeaveBelt()
			result = ok and result

			if result then
				local slicedn16 = slicedn15 + 4
				result = tbl4.DistanceTo(sliced11) <= slicedn16
			end

			return result
		end

		local sliced11 = slicedfn29

		local function slicedfn45(arg)
			if not arg then
				return 0
			end
			local num = tonumber(arg:GetAttribute("Uses"))
			if num ~= nil then
				return num
			end
			local sliced12 = string.match(arg.Name, "%[X(%d+)%]")
			return tonumber(sliced12) or 1
		end

		local function slicedfn46()
			local sliced12 = sliced11()
			if not sliced12 then
				return nil, 0
			end
			local sliced13 = slicedfn45(sliced12)
			if sliced13 <= 0 then
				return nil, 0
			end
			return sliced12, sliced13
		end

		tbl21.Grip = function(arg)
			local character = localPlayer.Character
			local humanoid = character and character:FindFirstChildOfClass("Humanoid")
			if not character or not humanoid or not arg or arg.Parent == nil then
				return false
			end

			if arg.Parent ~= character then
				pcall(function()
					humanoid:EquipTool(arg)
				end)

				if arg.Parent ~= character then
					pcall(function()
						arg.Parent = character
					end)
				end

				task.wait(0.2)
			end

			return arg.Parent == character
		end

		local function slicedfn47()
			if not tbl4.Toggle(tbl21.BuyHandle, false) or flag3 then
				return false
			end
			flag3 = true
			local flag4 = false

			local ok, result = pcall(function()
				flag4 = tbl21.Purchase()
			end)

			flag3 = false

			if not ok then
				tbl21.Status = "Buy failed: " .. tostring(result)
			end

			return flag4
		end

		tbl21.Purchase = function()
			local slicedn16 = 0
			local short = false

			for i = 1, 10 do
				local flag4 = slicedn16 == 0 and slicedfn9(true) or snapshot
				local sliced12 = slicedfn10()

				if not (type(flag4) ~= "table" or type(sliced12) ~= "table") then
					local sliced13, sliced14, sliced15 = ipairs(type(flag4.Shop) == "table" and flag4.Shop or {})
					local sliced16 = nil

					for _, sliced17 in sliced13, sliced14, sliced15 do
						if type(sliced17) == "table" and sliced17.Id == "MutationConsumable" then
							sliced16 = sliced17
						end
					end

					if sliced16 then
						local num = tonumber(sliced16.PurchaseLimit)

						if not (num and slicedfn30(sliced12, sliced16) >= num) then
							local huge = tonumber(sliced16.Price) or math.huge

							if (tonumber(sliced12.Samples) or 0) - huge < slicedn4 then
								short = true

								if slicedn16 == 0 then
									tbl21.Status = "Need " .. tostring(math.floor(huge)) .. " Samples"
								end

								break
							else
								local Shop = slicedfn8("Shop", sliced16.Id, { Quote = sliced16.Quote, Sequence = tonumber(sliced12.ShopSequence) or 0 })

								if not (type(Shop) ~= "table" or Shop.Ok ~= true) then
									slicedn16 += 1
									task.wait(0.4)
									continue
								end
							end
						end
					end
				end

				break
			end

			if slicedn16 > 0 then
				tbl21.Status = string.format("Bought %d Scrambled", slicedn16)
				tbl21.Short = short
				return true
			end

			tbl21.Short = short
			return false
		end

		local function slicedfn48()
			local pen = 0
			local match = 0
			local slicedn16 = -1
			local sliced12 = nil

			for _, sliced13 in ipairs(slicedfn42()) do
				pen += 1
				local skipMutated = tbl21.SkipMutated and slicedfn41(sliced13)
				local flag4 = false

				if skipMutated then
					flag4 = true
				end

				local flag5 = not flag4

				if flag5 then
					local minRarity = tbl21.MinRarity
					flag5 = slicedfn39(sliced13) < minRarity
				end

				if flag5 then
					flag4 = true
				end

				local flag6 = not flag4 and tbl21.MinIncome > 0

				if flag6 then
					local minIncome = tbl21.MinIncome
					flag6 = slicedfn40(sliced13) < minIncome
				end

				if flag6 then
					flag4 = true
				end

				if not flag4 and next(tbl21.Targets) ~= nil and tbl21.Targets[tostring(sliced13.AssetCategory)] ~= true then
					flag4 = true
				end

				if not flag4 then
					match += 1
					local slicedn17

					if tbl21.Priority == tbl19[2] then
						slicedn17 = slicedfn39(sliced13) * 1000 + (tonumber(sliced13.AssetScale) or 0)
					elseif tbl21.Priority == tbl19[3] then
						slicedn17 = tonumber(sliced13.AssetScale) or 0
					else
						slicedn17 = slicedfn40(sliced13)
					end

					local flag7 = slicedn17 > slicedn16

					if not flag7 and sliced12 ~= nil and slicedn17 == slicedn16 and sliced13.Uid == tbl21.Locked then
						slicedn16 = slicedn17
						sliced12 = sliced13
					elseif flag7 then
						slicedn16 = slicedn17
						sliced12 = sliced13
					end
				end
			end

			local sliced13 = tbl21
			tbl21.Pen = pen
			sliced13.Match = match
			return sliced12
		end

		local function slicedfn49(arg)
			if typeof(arg) ~= "Color3" then
				return "#FFFFFF"
			end
			return string.format("#%02X%02X%02X", math.floor(arg.R * 255 + 0.5), math.floor(arg.G * 255 + 0.5), math.floor(arg.B * 255 + 0.5))
		end

		local function slicedfn50(arg)
			local ok, result = pcall(Color3.fromHex, arg)
			if not ok or typeof(result) ~= "Color3" then
				return arg
			end
			local sliced12, sliced13, sliced14 = result:ToHSV()
			return slicedfn49(Color3.fromHSV(sliced12, math.min(sliced13, 0.78), math.max(sliced14, 0.82)))
		end

		local function slicedfn51(arg)
			local sliced12 = slicedfn38(arg and arg.AssetCategory)
			local icon = type(sliced12) == "table" and sliced12.Icon or nil
			if icon == nil then
				return ""
			end

			if tonumber(icon) then
				return "rbxassetid://" .. tostring(icon)
			end
			return tostring(icon)
		end

		local function slicedfn52(arg)
			local sliced12 = slicedfn38(arg and arg.AssetCategory)
			local rarity = type(sliced12) == "table" and sliced12.Rarity or nil
			local flag4 = type(rarity) == "table"

			if flag4 then
				flag4 = tostring(rarity.DisplayName or rarity._id or "")
			end

			flag4 = flag4 or ""
			local sliced13 = table.pack(slicedfn50(slicedfn49(type(rarity) == "table" and rarity.Color or nil)))
			return flag4, table.unpack(sliced13, 1, sliced13.n)
		end

		local function slicedfn53(arg)
			if type(arg) ~= "table" then
				return "No egg selected"
			end
			local sliced12 = slicedfn38(arg.AssetCategory)
			local flag4 = type(sliced12) == "table"

			if flag4 then
				flag4 = tostring(sliced12.DisplayName or arg.AssetCategory)
			end

			return flag4 or tostring(arg.AssetCategory)
		end

		local function slicedfn54()
			local idle = tbl20[tbl21.State] or tbl20.idle

			if tbl21.Ui.Accent and type(tbl21.Ui.Accent.Set) == "function" then
				tbl21.Ui.Accent.Set({ Background = idle })
			end

			if tbl21.Ui.Title and type(tbl21.Ui.Title.Set) == "function" then
				tbl21.Ui.Title.Set({ Text = tbl21.Status, Color = idle })
			end

			if tbl21.Ui.Egg and type(tbl21.Ui.Egg.Set) == "function" then
				tbl21.Ui.Egg.Set({ Text = tbl21.Detail, Color = tbl21.RarityColor })
			end

			if tbl21.Ui.Meta and type(tbl21.Ui.Meta.Set) == "function" then
				tbl21.Ui.Meta.Set({
					Text = string.format("Charges %d  Eggs %d/%d  Tries %d  Applied %d", tbl21.Left, tbl21.Match, tbl21.Pen, tbl21.Tries, tbl21.Hits),
				})
			end

			if tbl21.Ui.Icon and type(tbl21.Ui.Icon.Set) == "function" then
				tbl21.Ui.Icon.Set({ Visible = tbl21.Icon ~= "", Image = tbl21.Icon, StrokeColor = tbl21.RarityColor })
			end

			if tbl21.Row and type(tbl21.Row.Set) == "function" then
				pcall(tbl21.Row.Set, tbl21.Row, tbl21.Status .. "  -  " .. tbl21.Detail)
			end
		end

		local function slicedfn55(arg)
			if type(arg) ~= "table" then
				tbl21.Detail = "No egg matches the filters"
				tbl21.RarityColor = "#C7CBD6"
				tbl21.Icon = ""
				return
			end

			local sliced12, sliced13 = slicedfn52(arg)
			local slicedn16 = tonumber(arg.AssetScale) or 0
			tbl21.Detail = string.format("%s   %.2f kg", slicedfn53(arg), slicedn16)

			if sliced12 ~= "" then
				tbl21.Detail = tbl21.Detail .. "   " .. string.upper(sliced12)
			end

			tbl21.RarityColor = sliced13
			tbl21.Icon = slicedfn51(arg)
		end

		tbl21.Apply = function(arg, arg2)
			if not tbl21.Grip(arg2) then
				tbl21.State = "work"
				tbl21.Status = "Could not hold Scrambled"
				tbl21.Cooldown = os.clock() + 2
				return false
			end

			local packages = ReplicatedStorage:FindFirstChild("Packages")
			packages = packages and packages:FindFirstChild("Networking")
			local rfBossMasteryAskUseMutationConsu = packages and packages:FindFirstChild("RF/BossMastery/AskUseMutationConsumable")

			if not rfBossMasteryAskUseMutationConsu or not rfBossMasteryAskUseMutationConsu:IsA("RemoteFunction") then
				tbl21.State = "stop"
				tbl21.Status = "Mutation remote is missing"
				tbl21.Cooldown = os.clock() + 10
				return false
			end

			tbl21.State = "work"
			tbl21.Status = "Applying Scrambled"
			tbl21.Tries = tbl21.Tries + 1

			local ok, result = pcall(function()
				return rfBossMasteryAskUseMutationConsu:InvokeServer(arg.Uid)
			end)

			if not ok or type(result) ~= "table" then
				tbl21.Cooldown = os.clock() + 10
				return false
			end

			if result.Success == true then
				tbl21.Status = "Scrambled applied"
				tbl21.Locked = nil
				tbl21.State = "good"
				tbl21.Hits = tbl21.Hits + 1
				return true
			end

			local str3 = tostring(result.Message or "")
			local sliced12 = string.lower(str3)
			tbl21.Status = str3 ~= "" and str3 or "Try failed"
			tbl21.State = "work"

			if string.find(sliced12, "not found") or string.find(sliced12, "invalid") then
				tbl21.Locked = nil
				tbl21.Cooldown = os.clock() + 3
				return false
			end

			return true
		end

		tbl21.Settle = function()
			local slicedn16 = os.clock() + 3

			while os.clock() < slicedn16 do
				if tbl4.Grounded() then
					return
				end
				RunService.Heartbeat:Wait()
			end
		end

		tbl21.Over = function(arg)
			if arg ~= tbl21.Loop or not tbl4.Toggle(tbl21.Handle, false) then
				return true
			end

			if tbl4.Movement.PlaceWanted == true then
				return true
			end
			return tbl4.Movement.ScrambleWanted == true or tbl4.Steal.Wanted == true
		end

		tbl21.Idle = function(status, detail, arg)
			tbl21.State = "idle"
			tbl21.Status = status
			tbl21.Left = 0
			tbl21.Detail = detail
			tbl21.RarityColor = "#C7CBD6"
			tbl21.Icon = ""
			tbl21.Cooldown = os.clock() + (arg or 5)
		end

		local function slicedfn56(arg)
			if tbl4.Movement.ScrambleWanted == true or tbl4.Steal.Wanted == true then
				tbl21.State = "work"
				tbl21.Status = tbl4.Movement.ScrambleWanted == true and "Drone hunt goes first" or "Auto Steal goes first"
				tbl21.Cooldown = os.clock() + 2
				return
			end

			local cooldown = tbl21.Cooldown
			if os.clock() < cooldown then
				return
			end
			local sliced12, sliced13 = slicedfn46()

			if not sliced12 then
				pcall(slicedfn48)
				if slicedfn47() then
					tbl21.Cooldown = os.clock() + 0.5
					return
				end

				if tbl21.Short then
					tbl21.Idle("Out of Samples, waiting for more", "Hunt drones to earn Samples", 10)
					return
				end

				if not string.find(tbl21.Status, "Samples", 1, true) then
					tbl21.Status = "Need a Scrambled consumable"
				end

				tbl21.Idle(tbl21.Status, "Buy Scrambled from the event shop", 5)
				return
			end

			tbl21.Left = sliced13
			local sliced14 = slicedfn48()

			if not sliced14 or not sliced14.Uid then
				tbl21.State = "stop"
				tbl21.Status = "Waiting"
				slicedfn55(nil)
				return
			end

			if tbl4.Movement.PlaceWanted == true then
				tbl21.State = "work"
				tbl21.Status = "Auto Place goes first"
				tbl21.Cooldown = os.clock() + 2
				return
			end

			if not tbl4.ClaimMovement("mutation") then
				tbl21.State = "work"
				tbl21.Status = "Waiting for " .. tostring(tbl4.Movement.Owner or "movement")
				tbl21.Cooldown = os.clock() + 2
				return
			end

			tbl4.Movement.MutationWanted = true

			local ok, result = pcall(function()
				while not tbl21.Over(arg) do
					local sliced15, sliced16 = slicedfn46()

					if sliced15 then
						tbl21.Left = sliced16
						local sliced17 = slicedfn48()

						if not sliced17 or not sliced17.Uid then
							tbl21.State = "stop"
							tbl21.Status = "Waiting"
							slicedfn55(nil)
							break
						else
							if sliced17.Uid ~= tbl21.Locked then
								tbl21.Locked = sliced17.Uid
								tbl21.Status = "New target picked"
							end

							slicedfn55(sliced17)

							if not slicedfn44(sliced17, arg) then
								tbl21.State = "work"
								tbl21.Status = "Could not reach the egg"
								tbl21.Cooldown = os.clock() + 3
								break
							elseif not tbl21.Over(arg) then
								if tbl21.Apply(sliced17, sliced15) then
									pcall(slicedfn54)
									task.wait(0.35)
									continue
								end
							end
						end
					end

					break
				end
			end)

			if not ok then
				tbl21.Status = "Stopped: " .. tostring(result)
				tbl21.State = "work"
				tbl21.Cooldown = os.clock() + 3
			end

			tbl21.Settle()
			tbl4.Movement.MutationWanted = false
			tbl4.ReleaseMovement("mutation")
		end

		tbl21.Handle = sliced6:CreateToggle({
			Name = "Auto Use Scrambled Mutation",
			Default = false,
			Callback = function(arg)
				tbl21.Loop = tbl21.Loop + 1
				tbl4.Movement.MutationWanted = false
				tbl4.ReleaseMovement("mutation")
				if arg ~= true then
					return
				end
				local loop = tbl21.Loop

				task.spawn(function()
					while loop == tbl21.Loop and tbl4.Toggle(tbl21.Handle, false) do
						pcall(slicedfn56, loop)
						pcall(slicedfn54)
						task.wait(tbl21.State == "idle" and 3 or 1)
					end
				end)
			end,
		})

		if type(sliced6.CreateCanvas) == "function" then
			local sliced12 = sliced6:CreateCanvas({
				Name = "Scrambled Status",
				ShowTitle = false,
				Layout = "free",
				SubOf = tbl21.Handle,
				Style = {
					TextScale = 1,
					LineHeight = 1.1,
					MinLines = 4,
					MaxLines = 4,
					AutoHeight = true,
					BackgroundTransparency = 0.35,
					TextColor = Color3.fromRGB(255, 255, 255),
					TextStrokeTransparency = 0.7,
				},
				Build = function(arg)
					tbl21.Ui.Card = arg:Frame({
						X = 0,
						Y = 0,
						Width = 1,
						Height = 3.6,
						Corner = 0.3,
						Background = "#151821",
						BackgroundTransparency = 0.25,
					})

					tbl21.Ui.Accent = arg:Frame({
						Parent = tbl21.Ui.Card,
						X = 0.08,
						Y = 0.18,
						Width = 0.16,
						Height = 3.24,
						Corner = 0.2,
						Background = tbl20.idle,
					})

					tbl21.Ui.Icon = arg:Image({
						Parent = tbl21.Ui.Card,
						X = 0.42,
						Y = 0.3,
						Width = 3,
						Height = 3,
						Corner = 0.3,
						Background = "#242938",
						BackgroundTransparency = 0.1,
						StrokeThickness = 0.06,
						StrokeTransparency = 0,
						Visible = false,
					})

					tbl21.Ui.Title = arg:Text({
						Parent = tbl21.Ui.Card,
						X = 3.7,
						Y = 0.32,
						Width = 1,
						Height = 1.05,
						Scale = 1.16,
						Wrap = false,
						Text = tbl21.Status,
						Color = tbl20.idle,
						TextStrokeTransparency = 1,
					})

					tbl21.Ui.Egg = arg:Text({
						Parent = tbl21.Ui.Card,
						X = 3.7,
						Y = 1.42,
						Width = 1,
						Height = 1,
						Scale = 1,
						Wrap = false,
						Text = tbl21.Detail,
						Color = "#FFFFFF",
						TextStrokeTransparency = 1,
					})

					tbl21.Ui.Meta = arg:Text({
						Parent = tbl21.Ui.Card,
						X = 3.7,
						Y = 2.42,
						Width = 1,
						Height = 0.9,
						Scale = 0.86,
						Wrap = false,
						Text = "Charges 0  Eggs 0/0  Tries 0  Applied 0",
						Color = "#AEB4C6",
						TextStrokeTransparency = 1,
					})

					slicedfn54()
				end,
			})

			slicedfn4(function()
				pcall(function()
					sliced12:Destroy()
				end)
			end)
		else
			tbl21.Row = sliced6:CreateText({ Name = "Scrambled Status", Text = "Idle", SubOf = tbl21.Handle })
		end

		sliced6:CreateDropdown({
			Name = "Mutation Min Rarity",
			Note = "Only eggs of this rarity and above are used",
			Options = tbl8,
			Default = tbl8[1],
			SubOf = tbl21.Handle,
			Callback = function(arg)
				tbl21.MinRarity = tbl9[arg] or 0
			end,
		})

		local tbl23 = {
			["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
			["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
			["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
		}

		local tbl24 = { Slider = nil, Value = 0, Unit = "M/s" }

		local function slicedfn57(arg, arg2)
			if arg ~= nil then
				tbl24.Value = math.max(0, math.floor(tonumber(arg) or tbl24.Value))
			end

			if arg2 ~= nil then
				tbl24.Unit = tostring(arg2)
			end

			tbl21.MinIncome = tbl24.Value * (tbl23[tbl24.Unit] or tbl23["M/s"]).Mult
		end

		tbl24.Slider = slicedfn5(sliced6, {
			Name = "Min Mutation Value",
			Note = "Skip eggs worth less than this (0 = off)",
			SubOf = tbl21.Handle,
			Legacy = "Mutation Min Value",
			SectionName = "Dr Scramble Event",
			OnRaw = function(arg)
				slicedfn57(math.floor(arg / 1000), "K/s")
			end,
		})

		sliced6:CreateDropdown({
			Name = "Mutation Priority",
			Note = "Which egg gets the consumable first",
			Options = tbl19,
			Default = tbl19[1],
			SubOf = tbl21.Handle,
			Callback = function(arg)
				tbl21.Priority = tostring(arg)
			end,
		})

		slicedfn6(sliced6:CreateMultiDropdown({
			Name = "Mutation Target Eggs",
			Note = "Only use the consumable on these eggs (empty = all)",
			Options = tbl21.EggOptions,
			Default = {},
			SubOf = tbl21.Handle,
			Callback = function(arg)
				local targets = {}

				if type(arg) == "table" then
					for k, sliced12 in pairs(arg) do
						k = sliced12 == true and type(k) == "string" and k or type(sliced12) == "string" and sliced12
						local sliced13 = k or nil

						if sliced13 and tbl21.EggCategory[sliced13] then
							targets[tbl21.EggCategory[sliced13]] = true
						end
					end
				end

				tbl21.Targets = targets
			end,
		}))

		tbl21.BuyHandle = sliced6:CreateToggle({
			Name = "Auto Buy Scrambled",
			Note = "Buy another Scrambled from the event shop when you run out",
			Default = false,
			SubOf = tbl21.Handle,
			Callback = function()
				tbl21.Cooldown = 0
			end,
		})

		slicedfn4(function()
			tbl21.Loop = tbl21.Loop + 1
			tbl4.Movement.MutationWanted = false
			tbl4.ReleaseMovement("mutation")
		end)
	end

	do
		local slicedn15 = nil
		local flag4 = false
		local flag5 = false

		tbl3.Add(function()
			if not flag5 and os.clock() - slicedn5 >= n then
				flag5 = true

				task.spawn(function()
					pcall(slicedfn9, true)
					flag5 = false
				end)
			end

			local flag6 = nil

			if sliced8 then
				flag6 = type(sliced8.Set) == "function"
			end

			if flag6 then
				pcall(sliced8.Set, nil, slicedfn15())
			end

			local flag7 = nil

			if sliced10 then
				flag7 = type(sliced10.Set) == "function"
			end

			if flag7 then
				pcall(sliced10.Set, nil, slicedfn33())
			end

			local sliced11 = slicedfn12()
			local sliced12 = tbl4.IsNight()

			if sliced11 and not flag4 then
				tbl16.Latch = sliced12
				tbl16.Ended = false
			end

			if not sliced12 then
				tbl16.Latch = false
			elseif sliced11 and not tbl16.Latch and not tbl16.Ended then
				tbl16.Ended = true
				str = "Night arrived, this outbreak is over"
				table.clear(tbl12)
				table.clear(tbl13)
			end

			if not sliced11 then
				tbl16.Ended = false
			end

			if flag4 and not sliced11 then
				task.delay(15, function()
					if not slicedfn12() then
						table.clear(tbl12)
						table.clear(tbl18)
					end
				end)
			end

			flag4 = sliced11

			if tbl4.Toggle(nil, false) and not flag3 and os.clock() >= slicedn9 and slicedfn11() then
				flag3 = true
				slicedn9 = os.clock() + 8

				task.spawn(function()
					pcall(slicedfn31, function()
						return not tbl4.Toggle(nil, false)
					end)

					flag3 = false
				end)
			end

			local sliced13 = slicedfn34()
			local sliced14 = slicedfn35()
			tbl4.Movement.ScrambleWanted = sliced13 or sliced14
			local invisibilityHandle = tbl4.InvisibilityHandle
			local flag8 = invisibilityHandle ~= nil and tbl4.Toggle(invisibilityHandle, false)

			if sliced13 then
				slicedn15 = nil

				if not tbl4.InvisSuspended then
					tbl4.InvisSuspended = true
					flag8 = flag8 and type(v.Notify) == "function"

					if flag8 then
						pcall(v.Notify, "Invisibility", "Invisibility is paused for the drone hunt and comes back after it.", 5)
					end
				end
			elseif tbl4.InvisSuspended and not flag then
				slicedn15 = slicedn15 or os.clock() + 5

				if os.clock() >= slicedn15 then
					slicedn15 = nil
					tbl4.InvisSuspended = false

					if flag8 and type(v.Notify) == "function" then
						pcall(v.Notify, "Invisibility", "The drone hunt is over, Invisibility is back on.", 5)
					end
				end
			end

			local character = localPlayer.Character
			if sliced13 and not flag and character and character:GetAttribute("InvisApplied") == true then
				str = "Leaving Invisibility for the hunt"
				return true
			end

			if flag then
				return sliced13
			end

			if not (sliced13 or sliced14) or os.clock() < slicedn7 then
				if not sliced13 and not sliced14 then
					str = ""
				end

				return false
			end

			local steal = tbl4.Steal
			if steal.Active or steal.Carrying or steal.Wanted then
				str = "Auto Steal goes first"
				return sliced13
			end

			if not tbl4.ClaimMovement("scramble") then
				str = "Waiting for " .. tostring(tbl4.Movement.Owner or "movement") .. " to finish"
				return sliced13
			end
			flag = true
			slicedn7 = os.clock() + slicedn2
			local sliced15 = slicedn6

			task.spawn(function()
				pcall(slicedfn37, function()
					return sliced15 ~= slicedn6
				end)

				tbl4.HoldBelt()
				pcall(slicedfn36, sliced15)
				slicedfn32()
				tbl4.ReleaseBelt()
				tbl4.ReleaseMovement("scramble")
				flag = false
				tbl3.Wake()
			end)

			return sliced13
		end)
	end

	slicedfn4(function()
		slicedn6 += 1
		slicedfn32()
		tbl4.InvisSuspended = false
		tbl4.Movement.ScrambleWanted = false
		tbl4.ReleaseMovement("scramble")
	end)

	local sliced11, sliced12

	do
		local sliced13 = sliced2:CreateTab({ Name = "Player", SectionsExpanded = true })
		tbl4.EspSection = sliced13:CreateSection({ Name = "ESP", Expanded = false })
		local sliced14 = sliced13:CreateSection({ Name = "Movement", Expanded = true })
		sliced11 = sliced13:CreateSection({ Name = "Character", Expanded = true })
		sliced12 = sliced13:CreateSection({ Name = "Combat", Expanded = true })
		local createToggle = nil
		local slicedn15 = 350
		local connection = nil
		local flag4 = false

		local function slicedfn38()
			local character = localPlayer.Character
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			character = character and character:FindFirstChildOfClass("Humanoid")
			if humanoidRootPart and character and character.Health > 0 then
				return humanoidRootPart, character
			end
			return nil, nil
		end

		local function slicedfn39()
			if not flag4 then
				return
			end
			flag4 = false
			local sliced15, sliced16 = slicedfn38()
			if not sliced15 then
				return
			end
			local assemblyLinearVelocity = sliced15.AssemblyLinearVelocity
			local moveDirection = sliced16.MoveDirection
			local vector = Vector3.new(moveDirection.X, 0, moveDirection.Z)
			local vector2 = vector.Magnitude > 0.001 and vector.Unit * sliced16.WalkSpeed or Vector3.zero

			pcall(function()
				sliced15.AssemblyLinearVelocity = Vector3.new(vector2.X, assemblyLinearVelocity.Y, vector2.Z)
			end)
		end

		local function slicedfn40()
			if connection then
				connection:Disconnect()
				connection = nil
			end

			slicedfn39()
			tbl4.Shield("speed", false)
		end

		local function slicedfn41()
			if connection then
				return
			end
			tbl4.Shield("speed", true)

			connection = RunService.Heartbeat:Connect(function()
				if tbl4.Steal.Active or tbl4.Flying or tbl4.Driving > 0 or tbl4.Treadmill.Riding then
					flag4 = false
					return
				end
				local sliced15, sliced16 = slicedfn38()
				if not sliced15 or sliced16.Sit or sliced16.PlatformStand then
					flag4 = false
					return
				end
				local num = tonumber(localPlayer:GetAttribute("RagdollEndTime"))
				if num and num > workspace:GetServerTimeNow() then
					flag4 = false
					return
				end
				local moveDirection = sliced16.MoveDirection
				local vector = Vector3.new(moveDirection.X, 0, moveDirection.Z)
				if vector.Magnitude <= 0.001 then
					slicedfn39()
					return
				end
				local boost = slicedn15

				local sc = tbl4.SafeCarry

				if sc.StopMode or sc.Teleport or tbl4.Steal.Carrying then
					boost = math.min(boost, math.max(tbl4.WalkSpeed(), 16) * sc.Cap(math.huge))
				end
				local slicedn16 = vector.Unit * boost
				local assemblyLinearVelocity = sliced15.AssemblyLinearVelocity

				pcall(function()
					sliced15.AssemblyLinearVelocity = Vector3.new(slicedn16.X, assemblyLinearVelocity.Y, slicedn16.Z)
				end)

				flag4 = true
			end)
		end

		tbl4.SpeedForced = false

		local function slicedfn42()
			if tbl4.Toggle(createToggle, false) or tbl4.SpeedForced then
				slicedfn41()
			else
				slicedfn40()
			end
		end

		local flag5 = false
		local flag6 = false
		local flag7 = false

		tbl4.SetSpeedForced = function(arg)
			tbl4.SpeedForced = arg == true
			flag5 = true
			slicedfn42()
		end

		local tbl19 = {
			Name = "Speed Boost",
			Default = false,
			Callback = function()
				if (tbl4.SafeCarry.StopMode or tbl4.SafeCarry.Teleport) and tbl4.Toggle(createToggle, false) and SourcesLib and SourcesLib.Banner then
					SourcesLib.Banner((tbl4.SafeCarry.StopMode and "Delivery Stop" or "Instant TP") .. ": max 115%, faster = bug", 5)
				end
				if tbl4.SpeedForced and not tbl4.Toggle(createToggle, false) then
					flag5 = true
					flag7 = true
				end

				slicedfn42()
			end,
		}

		createToggle = sliced14.CreateToggle
		createToggle = createToggle(sliced14, tbl19)

		local connection2 = RunService.Heartbeat:Connect(function()
			if flag7 then
				flag7 = false

				if type(v.Notify) == "function" then
					pcall(v.Notify, "Speed Boost", "Speed Boost must stay on while Invisibility is on.", 5)
				end
			end

			if not flag5 then
				return
			end
			flag5 = false
			local flag8

			if tbl4.SpeedForced and not tbl4.Toggle(createToggle, false) then
				flag6 = true
				flag8 = true
			else
				local flag9 = not tbl4.SpeedForced and flag6
				flag8 = nil

				if flag9 then
					flag6 = false
					flag8 = nil

					if tbl4.Toggle(createToggle, false) then
						flag8 = false
					end
				end
			end

			if flag8 ~= nil then
				for _, sliced15 in ipairs({ "Set", "SetValue" }) do
					local ok, result = pcall(function()
						return createToggle[sliced15]
					end)

					if not (ok and type(result) == "function" and pcall(result, createToggle, flag8)) then
						continue
					end
					break
				end
			end
		end)

		slicedfn4(function()
			connection2:Disconnect()
		end)

		sliced14:CreateSlider({
			Name = "Boost Speed",
			Min = 20,
			Max = 1000,
			Default = 350,
			Increment = 5,
			Unit = "studs/s",
			Callback = function(arg)
				slicedn15 = math.clamp(tonumber(arg) or 350, 20, 1000)
			end,
		})

		slicedfn4(slicedfn40)
		local sliced15 = nil
		local connection3 = nil

		local function slicedfn43()
			if connection3 then
				connection3:Disconnect()
				connection3 = nil
			end

			tbl4.Shield("jump", false)
		end

		sliced15 = sliced14:CreateToggle({
			Name = "Infinite Jump",
			Default = false,
			Callback = function()
				if not tbl4.Toggle(sliced15, false) then
					slicedfn43()
					return
				end

				if connection3 then
					return
				end
				tbl4.Shield("jump", true)

				connection3 = UserInputService.JumpRequest:Connect(function()
					local character = localPlayer.Character
					local humanoid = character and character:FindFirstChildOfClass("Humanoid")

					if humanoid then
						pcall(function()
							humanoid:ChangeState(Enum.HumanoidStateType.Jumping)
						end)
					end
				end)
			end,
		})

		slicedfn4(slicedfn43)
	end

	do
		local sliced13 = nil
		local flag4 = false
		local flag5 = true
		local flag6 = false
		local flag7 = false
		local flag8 = false
		local sliced14 = nil
		local sliced15 = nil
		local hipHeight = 999

		local function slicedfn38()
			return flag4 and not tbl4.InvisSuspended and not tbl4.InvisMech
		end

		local function slicedfn39(arg)
			return arg and arg:FindFirstChildOfClass("Humanoid") or nil
		end

		local function slicedfn40(arg)
			return networking:FindFirstChild(arg)
		end

		local function slicedfn41(arg)
			return arg ~= nil and arg:GetAttribute("InvisApplied") == true
		end

		local function slicedfn42()
			local AskDoff = slicedfn40("RF/Treadmill/AskDoff")

			if AskDoff and AskDoff:IsA("RemoteFunction") then
				for i = 1, 2 do
					pcall(AskDoff.InvokeServer, AskDoff)
				end
			end
		end

		local function slicedfn43(arg)
			local AskRigWipe = slicedfn40("RE/RigSync/AskRigWipe")

			if AskRigWipe and AskRigWipe:IsA("RemoteEvent") then
				pcall(AskRigWipe.FireServer, AskRigWipe, arg)
			end
		end

		local function slicedfn44(arg)
			local backpack = localPlayer:FindFirstChildOfClass("Backpack")

			for _, child in ipairs(arg:GetChildren()) do
				if child:IsA("Humanoid") then
					pcall(child.UnequipTools, child)
				end
			end

			if backpack then
				for _, child in ipairs(arg:GetChildren()) do
					if child:IsA("Tool") then
						pcall(function()
							child.Parent = backpack
						end)
					end
				end
			end

			for i = 1, 3 do
				RunService.Heartbeat:Wait()
			end
		end

		local function slicedfn45(arg)
			local sliced16 = slicedfn39(arg)
			if not arg or not sliced16 then
				return false
			end
			slicedfn44(arg)
			slicedfn42()

			pcall(function()
				sliced16:SetStateEnabled(Enum.HumanoidStateType.Dead, true)
				sliced16.BreakJointsOnDeath = true
				sliced16.RequiresNeck = true
				sliced16.Health = 0
			end)

			pcall(function()
				sliced16:ChangeState(Enum.HumanoidStateType.Dead)
			end)

			pcall(function()
				arg:BreakJoints()
			end)

			slicedfn43(arg)
			return true
		end

		local function slicedfn46(parent)
			local sliced16 = slicedfn39(parent)
			local slicedn15 = os.clock() + 10

			while true do
				if os.clock() < slicedn15 and flag5 and parent.Parent then
					sliced16 = sliced16 or slicedfn39(parent)
					if not (sliced16 and parent:FindFirstChild("HumanoidRootPart") and parent:FindFirstChild("Head")) then
						task.wait()
						continue
					end
				end

				break
			end

			local humanoidRootPart = parent:FindFirstChild("HumanoidRootPart")
			if not slicedfn38() or not sliced16 or not humanoidRootPart or not parent:FindFirstChild("Head") then
				return false
			end
			task.wait(0.05)
			if not slicedfn38() or parent.Parent == nil then
				return false
			end

			for i = 1, 2 do
				pcall(sliced16.UnequipTools, sliced16)
			end

			if type(replicatesignal) == "function" then
				for i = 1, 2 do
					pcall(replicatesignal, sliced16.ServerBreakJoints)
				end
			end

			local hipHeight2 = sliced16.HipHeight

			pcall(function()
				sliced16.HipHeight = hipHeight
			end)

			for _, child in ipairs(parent:GetChildren()) do
				if child:IsA("Accessory") or child:IsA("BasePart") and child ~= humanoidRootPart then
					pcall(function()
						child.Parent = nil
					end)
				end
			end

			task.wait(0.12)

			local function slicedfn47()
				pcall(function()
					sliced16.HipHeight = hipHeight2
				end)

				for _, child in ipairs(parent:GetChildren()) do
					if child:IsA("Humanoid") and child.HipHeight ~= hipHeight2 then
						pcall(function()
							child.HipHeight = hipHeight2
						end)
					end
				end
			end

			if parent.Parent == nil then
				slicedfn47()
				return false
			end
			local motor6D = Instance.new("Motor6D")
			motor6D.Name = "RightWrist"
			motor6D.C0 = CFrame.new(1.2, 0, 0)
			motor6D.C1 = CFrame.new()
			motor6D.Part0 = humanoidRootPart
			motor6D.Parent = humanoidRootPart
			local part = Instance.new("Part")
			part.Name = "RightHand"
			part.Size = Vector3.new(0.2, 0.2, 0.2)
			part.Transparency = 1
			part.CanCollide = false
			part.CanTouch = false
			part.CanQuery = false
			part.Massless = true
			part.CFrame = humanoidRootPart.CFrame * motor6D.C0
			motor6D.Part1 = part
			part.Parent = parent

			pcall(function()
				humanoidRootPart.CanCollide = false
			end)

			slicedfn47()
			parent:SetAttribute("InvisApplied", true)

			task.delay(1, function()
				local SourcesToolKeeper = (typeof(getgenv) == "function" and getgenv() or _G).SourcesToolKeeper

				if parent.Parent and type(SourcesToolKeeper) == "function" then
					pcall(SourcesToolKeeper)
				end
			end)

			task.delay(0.2, function()
				if humanoidRootPart.Parent then
					pcall(function()
						humanoidRootPart.CanCollide = true
					end)
				end
			end)

			local connection = parent.ChildAdded:Connect(function(child)
				if child:IsA("Humanoid") then
					task.defer(function()
						if child.HipHeight ~= hipHeight2 then
							pcall(function()
								child.HipHeight = hipHeight2
							end)
						end
					end)
				end
			end)

			local connection2 = nil

			connection2 = parent.AncestryChanged:Connect(function(child, parent2)
				if parent2 == nil then
					connection:Disconnect()
					connection2:Disconnect()
				end
			end)

			return true
		end

		local function slicedfn47()
			local active = tbl4.Steal.Active or tbl4.Steal.Carrying or tbl4.Flying

			if not active then
				active = (tbl4.Driving or 0) > 0
			end

			return active
		end

		tbl4.RequestRespawn = function()
			flag8 = true
		end

		local function slicedfn48()
			flag6 = true
			local sliced16 = flag8

			while true do
				local flag9 = flag5

				if flag5 then
					flag9 = slicedfn47() or not tbl4.ClaimMovement("invisibility")
				end

				if flag9 then
					task.wait(0.2)
					continue
				end
				break
			end

			local character = localPlayer.Character

			if flag5 and character and (sliced16 or slicedfn41(character) ~= slicedfn38()) and slicedfn39(character) then
				flag8 = false
				tbl7.Paused = true
				tbl4.ShieldPaused = true
				pcall(tbl4.UndoSwap)
				task.wait()
				slicedfn45(localPlayer.Character)
				local slicedn15 = os.clock() + 60
				local slicedn16 = os.clock() + 8

				while flag5 and os.clock() < slicedn15 and localPlayer.Character == character do
					if slicedn16 <= os.clock() then
						slicedn16 = os.clock() + 8
						slicedfn43(character)
					end

					task.wait(0.05)
				end

				task.wait(0.1)

				while flag5 and flag7 do
					task.wait(0.05)
				end
			end

			tbl7.Paused = false
			tbl4.ShieldPaused = false
			tbl4.ReleaseMovement("invisibility")
			flag6 = false
		end

		local connection = localPlayer.CharacterAdded:Connect(function(character)
			if not slicedfn38() then
				return
			end
			flag7 = true
			tbl4.ShieldPaused = true

			task.spawn(function()
				pcall(slicedfn46, character)
				flag7 = false

				if not flag6 then
					tbl4.ShieldPaused = false
				end
			end)
		end)

		local thread = task.spawn(function()
			while flag5 do
				local character = localPlayer.Character
				local sliced16 = slicedfn39(character)

				if not flag6 and not flag7 and character and sliced16 and sliced16.Health > 0 and (flag8 or slicedfn41(character) ~= slicedfn38()) then
					slicedfn48()
				end

				local sliced17 = slicedfn41(localPlayer.Character)

				if sliced17 ~= sliced14 then
					sliced14 = sliced17
					tbl4.SetSpeedForced(sliced17)
				end

				task.wait(0.25)
			end
		end)

		local connection2 = RunService.Heartbeat:Connect(function()
			local character = localPlayer.Character
			if not character or not slicedfn41(character) then
				return
			end
			local rightHand = character:FindFirstChild("RightHand")
			local tool = character:FindFirstChildWhichIsA("Tool")
			local handle = tool and tool:FindFirstChild("Handle")
			if not rightHand or not handle or not handle:IsA("BasePart") then
				return
			end
			local cframe = CFrame.new()

			for _, child in ipairs(rightHand:GetChildren()) do
				if child:IsA("JointInstance") and child.Name == "RightGrip" and child.Part1 == handle then
					cframe = child.C0 * child.C1:Inverse()

					if child.Enabled then
						child.Enabled = false
					end
				end
			end

			pcall(function()
				handle.CFrame = rightHand.CFrame * cframe
				handle.AssemblyLinearVelocity = Vector3.zero
				handle.AssemblyAngularVelocity = Vector3.zero
			end)
		end)

		slicedfn4(function()
			connection2:Disconnect()
		end)

		local connection3 = RunService.Heartbeat:Connect(function()
			local character = localPlayer.Character
			local sliced16 = slicedfn39(character)
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			if not sliced16 or not humanoidRootPart or sliced16.Health <= 0 then
				return
			end
			local flag9 = slicedfn41(character) and not tbl4.Steal.Active and not tbl4.Flying

			if flag9 then
				flag9 = (tbl4.Driving or 0) == 0
			end

			if flag9 then
				flag9 = not (tbl4.Treadmill and tbl4.Treadmill.Riding)
			end

			if not (flag9 and not sliced16.Sit and not sliced16.PlatformStand) then
				if sliced15 == sliced16 then
					sliced15 = nil

					pcall(function()
						sliced16.AutoRotate = true
					end)
				end

				return
			end

			if sliced16.AutoRotate then
				pcall(function()
					sliced16.AutoRotate = false
				end)
			end

			sliced15 = sliced16
			local moveDirection = sliced16.MoveDirection
			local vector = Vector3.new(moveDirection.X, 0, moveDirection.Z)

			if vector.Magnitude > 0.01 then
				pcall(function()
					humanoidRootPart.CFrame = CFrame.lookAt(humanoidRootPart.Position, humanoidRootPart.Position + vector.Unit)
				end)
			end
		end)

		tbl4.InvisibilityHandle = sliced11:CreateToggle({
			Name = "Invisibility",
			Note = "Makes you invisible to other players",
			Default = false,
			Callback = function()
				local str3 = nil

				if type(tbl4.CombatActive) == "function" and tbl4.CombatActive() then
					str3 = "Auto Hit"
				end

				if tbl4.Toggle(sliced13, false) and str3 then
					flag4 = false
					local sliced16 = sliced13

					tbl4.UiDefer(function()
						pcall(sliced16.Set, sliced16, false, false)
						tbl4.Notify("Invisibility", "Turn off " .. str3 .. " first, both cannot be on at the same time")
					end)

					return
				end

				flag4 = tbl4.Toggle(sliced13, false) == true

				if slicedfn38() and not slicedfn41(localPlayer.Character) and tbl4.Movement.Owner == nil then
					tbl4.Movement.Owner = "invisibility"
				end
			end,
		})

		slicedfn4(function()
			flag5 = false
			connection:Disconnect()
			connection3:Disconnect()
			pcall(task.cancel, thread)
			tbl7.Paused = false
			tbl4.ShieldPaused = false
			tbl4.ReleaseMovement("invisibility")
		end)
	end

	do
		local tbl19 = { BallSocketConstraint = true, NoCollisionConstraint = true, HingeConstraint = true }

		local tbl20 = {
			[Enum.HumanoidStateType.Physics] = true,
			[Enum.HumanoidStateType.Ragdoll] = true,
			[Enum.HumanoidStateType.FallingDown] = true,
		}

		local slicedn15 = 0.5
		local slicedn16 = 5
		local slicedn17 = 0

		local sliced13 = slicedfn2(function()
			return ReplicatedStorage.Shared.Modules.Ragdoll
		end)

		local sliced14 = nil

		local function slicedfn38()
			if sliced14 then
				return sliced14
			end

			local ok, result = pcall(function()
				return require(localPlayer:WaitForChild("PlayerScripts", 5):WaitForChild("PlayerModule", 5)):GetControls()
			end)

			if ok then
				sliced14 = result
			end

			return sliced14
		end

		local createToggle = nil
		local flag4 = false
		local connection = nil
		local slicedn18 = 0
		local slicedfn39 = nil
		local tbl21 = {}
		local tbl22 = {}
		local slicedn19 = 0
		local sliced15 = nil
		local humanoid = nil

		local function slicedfn40(arg)
			for _, sliced16 in ipairs(arg) do
				if sliced16.Connected then
					sliced16:Disconnect()
				end
			end

			table.clear(arg)
		end

		local function slicedfn41(arg)
			tbl21[#tbl21 + 1] = arg
		end

		local function slicedfn42(arg)
			tbl22[#tbl22 + 1] = arg
		end

		local function slicedfn43()
			if not sliced15 or not humanoid then
				return
			end
			local humanoidRootPart = sliced15:FindFirstChild("HumanoidRootPart")
			if not humanoidRootPart then
				return
			end
			local assemblyLinearVelocity = humanoidRootPart.AssemblyLinearVelocity
			local vector = Vector3.new(assemblyLinearVelocity.X, 0, assemblyLinearVelocity.Z)
			local slicedn20 = humanoid.WalkSpeed + slicedn16
			local y = assemblyLinearVelocity.Y
			local flag5 = false

			if slicedn20 < vector.Magnitude then
				vector = vector.Unit * slicedn20
				flag5 = true
			end

			if y > slicedn17 then
				y = slicedn17
				flag5 = true
			end

			if flag5 then
				pcall(function()
					humanoidRootPart.AssemblyLinearVelocity = Vector3.new(vector.X, y, vector.Z)
				end)
			end
		end

		local function slicedfn44()
			if type(sliced13) ~= "table" then
				return
			end

			if type(sliced13.ClearClientRagdoll) == "function" then
				pcall(sliced13.ClearClientRagdoll)
			end

			if type(sliced13.Unragdoll) == "function" then
				pcall(sliced13.Unragdoll, sliced15)
			end
		end

		local function slicedfn45()
			if not sliced15 or not sliced15.Parent then
				return
			end

			for _, descendant in ipairs(sliced15:GetDescendants()) do
				if tbl19[descendant.ClassName] then
					pcall(function()
						descendant:Destroy()
					end)
				end
			end
		end

		local function slicedfn46()
			if not sliced15 or not sliced15.Parent then
				return
			end

			for _, descendant in ipairs(sliced15:GetDescendants()) do
				if descendant:IsA("Motor6D") and not descendant.Enabled then
					pcall(function()
						descendant.Enabled = true
					end)
				elseif descendant:IsA("AnimationConstraint") and not descendant.Enabled then
					pcall(function()
						descendant.Enabled = true
					end)
				end
			end
		end

		local function slicedfn47()
			local sliced16 = slicedfn38()

			if sliced16 and sliced16.controlsEnabled == false then
				pcall(function()
					sliced16:Enable()
				end)
			end
		end

		local function slicedfn48()
			local currentCamera = workspace.CurrentCamera

			if currentCamera and humanoid and currentCamera.CameraSubject ~= humanoid then
				pcall(function()
					currentCamera.CameraSubject = humanoid
				end)
			end
		end

		local function slicedfn49()
			if not humanoid or not humanoid.Parent or humanoid.Health <= 0 then
				return
			end

			if tbl20[humanoid:GetState()] then
				pcall(function()
					humanoid:ChangeState(Enum.HumanoidStateType.Running)
				end)
			end

			if humanoid.PlatformStand then
				humanoid.PlatformStand = false
			end
		end

		local function slicedfn50()
			if type(sliced13) == "table" and type(sliced13.IsRagdolled) == "function" then
				local ok, result = pcall(sliced13.IsRagdolled, sliced15)
				if ok and result == true then
					return true
				end
			end

			local num = tonumber(localPlayer:GetAttribute("RagdollEndTime"))
			return num ~= nil and num > workspace:GetServerTimeNow()
		end

		local slicedn20 = 21

		local function slicedfn51()
			if tbl4.AntiGuard.Busy == true then
				return true
			end

			if (tonumber(tbl4.AntiGuard.HitArms) or 0) <= 0 then
				return false
			end
			return os.clock() - (tonumber(tbl4.AntiGuard.HitArmedAt) or 0) <= slicedn20
		end

		local function slicedfn52()
			if not humanoid or not humanoid.Parent then
				return false
			end

			if humanoid.PlatformStand then
				return true
			end
			return tbl20[humanoid:GetState()] == true
		end

		local function slicedfn53()
			if not sliced15 or not sliced15.Parent then
				return false
			end

			for _, child in ipairs(sliced15:GetChildren()) do
				if tbl19[child.ClassName] then
					return true
				end

				if child:IsA("BasePart") then
					for _, child2 in ipairs(child:GetChildren()) do
						if tbl19[child2.ClassName] then
							return true
						end
					end
				end
			end

			return false
		end

		local function slicedfn54()
			slicedfn43()
			slicedfn44()
			slicedfn45()
			slicedfn46()
			slicedfn49()
			slicedfn47()
			slicedfn48()
		end

		local function slicedfn55()
			if not flag4 or slicedfn51() then
				return
			end
			slicedn18 = os.clock() + slicedn15
		end

		local function slicedfn56()
			local character = localPlayer.Character

			if character ~= sliced15 then
				if character then
					slicedfn39(character)
				else
					slicedn19 += 1
					slicedfn40(tbl22)
					sliced15 = nil
					humanoid = nil
				end

				return
			end

			if not sliced15 then
				return
			end

			if sliced15:FindFirstChildOfClass("Humanoid") ~= humanoid then
				slicedfn39(sliced15)
			end
		end

		local function slicedfn57()
			if not flag4 then
				return
			end
			slicedfn56()
			if not sliced15 or not humanoid or humanoid.Health <= 0 then
				return
			end

			if slicedfn51() then
				slicedn18 = 0
				return
			end
			local now = os.clock()

			local scan = tbl4.ArScan
			if not scan or now - scan.At > 0.1 then
				scan = { At = now, Value = slicedfn53() }
				tbl4.ArScan = scan
			end

			if slicedfn52() or slicedfn50() or scan.Value then
				slicedn18 = now + slicedn15
			end

			if now <= slicedn18 then
				slicedfn54()
			end
		end

		slicedfn39 = function(arg)
			slicedn19 += 1
			local sliced16 = slicedn19
			slicedfn40(tbl22)
			sliced15 = arg
			humanoid = nil
			if not flag4 or not arg then
				return
			end
			humanoid = arg:FindFirstChildOfClass("Humanoid")
			if not flag4 or slicedn19 ~= sliced16 or arg ~= localPlayer.Character or not humanoid or not humanoid:IsA("Humanoid") then
				return
			end

			slicedfn42(humanoid.StateChanged:Connect(function(old, new)
				if flag4 and tbl20[new] then
					slicedfn55()
				end
			end))

			slicedfn42(humanoid:GetPropertyChangedSignal("PlatformStand"):Connect(function()
				if flag4 and humanoid and humanoid.PlatformStand then
					slicedfn55()
				end
			end))

			slicedfn42(arg.DescendantAdded:Connect(function(descendant)
				if flag4 and tbl19[descendant.ClassName] then
					slicedfn55()
				end
			end))

			slicedfn42(arg.ChildAdded:Connect(function(child)
				if flag4 and child:IsA("Humanoid") and child ~= humanoid then
					task.defer(slicedfn56)
				end
			end))

			slicedfn48()

			if slicedfn50() then
				slicedfn55()
			end
		end

		local function slicedfn58()
			flag4 = false
			slicedn19 += 1
			slicedn18 = 0

			if connection then
				pcall(function()
					connection:Disconnect()
				end)

				connection = nil
			end

			slicedfn40(tbl22)
			slicedfn40(tbl21)
			sliced15 = nil
			humanoid = nil
		end

		local function slicedfn59()
			slicedfn58()
			flag4 = true
			slicedfn38()
			connection = RunService.Heartbeat:Connect(slicedfn57)

			slicedfn41(localPlayer.CharacterAdded:Connect(function(character)
				if flag4 then
					task.defer(function()
						if flag4 and character == localPlayer.Character then
							slicedfn39(character)
						end
					end)
				end
			end))

			slicedfn41(localPlayer.CharacterRemoving:Connect(function(character)
				if flag4 and character == sliced15 then
					slicedn19 += 1
					slicedn18 = 0
					slicedfn40(tbl22)
					sliced15 = nil
					humanoid = nil
				end
			end))

			slicedfn41(localPlayer:GetAttributeChangedSignal("RagdollEndTime"):Connect(function()
				if flag4 then
					slicedfn55()
				end
			end))

			local clientRagdollRemote = type(sliced13) == "table" and sliced13.ClientRagdollRemote or nil

			if typeof(clientRagdollRemote) == "Instance" and clientRagdollRemote:IsA("RemoteEvent") then
				slicedfn41(clientRagdollRemote.OnClientEvent:Connect(function()
					if flag4 and not slicedfn51() then
						slicedfn43()
						slicedfn55()
					end
				end))
			end

			slicedfn41(tbl4.OnHumanoidChanged(function()
				if flag4 and localPlayer.Character then
					slicedfn39(localPlayer.Character)
				end
			end))

			if localPlayer.Character then
				slicedfn39(localPlayer.Character)
			end
		end

		slicedfn4(slicedfn58)

		local tbl23 = {
			Name = "Anti Ragdoll",
			Default = true,
			Callback = function()
				if tbl4.Toggle(createToggle, false) then
					slicedfn59()
				else
					slicedfn58()
				end
			end,
		}

		createToggle = sliced11.CreateToggle
		createToggle = createToggle(sliced11, tbl23)
	end

	do
		local flag4 = false
		local tbl19 = {}

		local function slicedfn38()
			for _, sliced13 in ipairs(tbl19) do
				pcall(function()
					sliced13:Disconnect()
				end)
			end

			table.clear(tbl19)
		end

		local function slicedfn39(arg)
			if flag4 and arg.Parent and arg.Health > 0 and arg.Health < arg.MaxHealth then
				pcall(function()
					arg.Health = arg.MaxHealth
				end)
			end
		end

		local function slicedfn40(arg)
			slicedfn38()
			if not flag4 or not arg then
				return
			end
			local humanoid = arg:FindFirstChildOfClass("Humanoid") or arg:WaitForChild("Humanoid", 5)
			if not flag4 or not humanoid or not humanoid:IsA("Humanoid") or arg ~= localPlayer.Character then
				return
			end

			table.insert(tbl19, humanoid.HealthChanged:Connect(function()
				slicedfn39(humanoid)
			end))

			table.insert(tbl19, RunService.Heartbeat:Connect(function()
				slicedfn39(humanoid)
			end))

			slicedfn39(humanoid)
		end

		local connection = localPlayer.CharacterAdded:Connect(function(character)
			if flag4 then
				task.defer(slicedfn40, character)
			end
		end)

		local sliced13 = tbl4.OnHumanoidChanged(function()
			if flag4 and localPlayer.Character then
				slicedfn40(localPlayer.Character)
			end
		end)

		slicedfn4(function()
			flag4 = false
			connection:Disconnect()
			sliced13:Disconnect()
			slicedfn38()
		end)

		flag4 = true

		if localPlayer.Character then
			task.spawn(slicedfn40, localPlayer.Character)
		end
	end

	do
		local sliced13 = nil
		local flag4 = true
		local tbl19 = {}
		local tbl20 = {}

		local function slicedfn38(arg)
			if arg:IsA("BasePart") and tbl19[arg] == nil then
				tbl19[arg] = arg.CanTouch

				pcall(function()
					arg.CanTouch = false
				end)
			end
		end

		local function slicedfn39(arg)
			if not flag4 or not arg.Parent then
				return
			end
			local name = localPlayer.Name
			if arg:GetAttribute("Owner") == name then
				return
			end
			slicedfn38(arg)

			for _, descendant in ipairs(arg:GetDescendants()) do
				slicedfn38(descendant)
			end

			table.insert(tbl20, arg.DescendantAdded:Connect(function(descendant)
				if flag4 then
					slicedfn38(descendant)
				end
			end))
		end

		local function slicedfn40()
			for _, sliced14 in ipairs(CollectionService:GetTagged("PlacedTrap")) do
				slicedfn39(sliced14)
			end
		end

		local function slicedfn41()
			for k, sliced14 in pairs(tbl19) do
				if k.Parent then
					pcall(function()
						k.CanTouch = sliced14
					end)
				end
			end

			table.clear(tbl19)
		end

		table.insert(tbl20, CollectionService:GetInstanceAddedSignal("PlacedTrap"):Connect(function(arg)
			task.defer(slicedfn39, arg)
		end))

		sliced13 = sliced11:CreateToggle({
			Name = "Anti Trap",
			Note = "Traps from other players cannot catch you",
			Default = true,
			Callback = function()
				flag4 = tbl4.Toggle(sliced13, true) == true

				if flag4 then
					slicedfn40()
				else
					slicedfn41()
				end
			end,
		})

		slicedfn40()

		slicedfn4(function()
			flag4 = false

			for _, sliced14 in ipairs(tbl20) do
				pcall(function()
					sliced14:Disconnect()
				end)
			end

			table.clear(tbl20)
			slicedfn41()
		end)
	end

	do
		local sliced13 = nil
		local str3 = "CarryAreaEgg"
		local tbl19 = { ClaimLostPart = true }
		local tbl20 = {}
		local connection = nil
		local connection2 = nil

		local function slicedfn38(arg)
			if not arg:IsA("ProximityPrompt") or tbl19[arg.Name] then
				return
			end

			if tbl20[arg] == nil then
				if arg.HoldDuration <= 0 and arg.Name ~= str3 then
					return
				end
				tbl20[arg] = arg.HoldDuration
			end

			if arg.HoldDuration ~= 0 then
				pcall(function()
					arg.HoldDuration = 0
				end)
			end
		end

		local function slicedfn39(arg)
			if arg.Name ~= "SmartPromptPart" then
				return nil
			end
			local carryAreaEgg = arg:FindFirstChild("CarryAreaEgg")
			return carryAreaEgg and carryAreaEgg:IsA("ProximityPrompt") and carryAreaEgg or nil
		end

		tbl4.PromptHold = function(arg)
			local sliced14 = tbl20[arg]
			if type(sliced14) == "number" then
				return sliced14
			end
			return arg.HoldDuration
		end

		local function slicedfn40()
			if connection then
				return
			end

			connection2 = ProximityPromptService.PromptShown:Connect(function(arg)
				if tbl4.Toggle(sliced13, true) then
					slicedfn38(arg)
				end
			end)

			for _, child in ipairs(workspace:GetChildren()) do
				local sliced14 = slicedfn39(child)

				if sliced14 then
					slicedfn38(sliced14)
				end
			end

			connection = workspace.ChildAdded:Connect(function(child)
				if child.Name ~= "SmartPromptPart" then
					return
				end

				task.defer(function()
					local carryAreaEgg = child:FindFirstChild("CarryAreaEgg") or child:WaitForChild("CarryAreaEgg", 2)

					if carryAreaEgg and carryAreaEgg:IsA("ProximityPrompt") and tbl4.Toggle(sliced13, true) then
						slicedfn38(carryAreaEgg)
					end
				end)
			end)
		end

		local function slicedfn41()
			for k, sliced14 in pairs(tbl20) do
				if k and k.Parent then
					pcall(function()
						k.HoldDuration = sliced14
					end)
				end
			end

			table.clear(tbl20)

			if connection then
				connection:Disconnect()
				connection = nil
			end

			if connection2 then
				connection2:Disconnect()
				connection2 = nil
			end
		end

		tbl4.PressStealPrompt = function(arg)
			if typeof(fireproximityprompt) ~= "function" or not arg then
				return false
			end
			local sliced14 = nil
			local huge = math.huge

			for _, child in ipairs(workspace:GetChildren()) do
				local sliced15 = slicedfn39(child)

				if sliced15 and child:IsA("BasePart") then
					local magnitude = (child.Position - arg).Magnitude

					if magnitude < huge then
						sliced14 = sliced15
						huge = magnitude
					end
				end
			end

			if not sliced14 or huge > 14 then
				return false
			end

			if tbl4.Toggle(sliced13, true) then
				pcall(function()
					sliced14.HoldDuration = 0
				end)
			end

			local ok = pcall(fireproximityprompt, sliced14)

			if ok and sliced14.HoldDuration > 0 then
				task.wait(sliced14.HoldDuration + 0.1)
			end

			return ok
		end

		tbl3.Add(function()
			if tbl4.Toggle(sliced13, true) then
				slicedfn40()

				for k in pairs(tbl20) do
					if not k.Parent then
						tbl20[k] = nil
					elseif k.HoldDuration ~= 0 then
						pcall(function()
							k.HoldDuration = 0
						end)
					end
				end
			elseif next(tbl20) ~= nil or connection then
				slicedfn41()
			end

			return false
		end)

		sliced13 = sliced11:CreateToggle({
			Name = "Instant Prompts",
			Default = true,
			Callback = function()
				tbl3.Wake()
			end,
		})

		slicedfn4(slicedfn41)
	end

	tbl4.Combat = {}

	do
		local combat = tbl4.Combat
		local slicedn15 = 15
		local slicedn16 = 2
		local slicedn17 = 0.05
		local slicedn18 = 1
		local slicedn19 = 0.18
		local slicedn20 = -0.275
		local slicedn21 = 0.6
		local slicedn22 = 6
		local slicedn23 = 1.1
		local slicedn24 = 0.8
		local slicedn25 = 2.5
		local slicedn26 = 35
		local slicedn27 = 0.12
		local slicedn28 = 6
		local slicedn29 = 6
		local slicedn30 = 3
		local tbl19 = { 0.12, 0.2, 0.28, 0.36, 0.46, 0.6 }
		local tbl20 = { ["WALL LEFT"] = true, ["WALL RIGHT"] = true }

		local tbl21 = {
			Trigger = nil,
			LastFire = 0,
			Trace = 0,
			EquipAt = 0,
			Walls = {},
			WallsAt = 0,
			WallSide = setmetatable({}, { __mode = "k" }),
			Tracks = setmetatable({}, { __mode = "k" }),
			Stats = {},
			Option = 3,
			Pending = {},
			Holders = {},
			SpawnRagdoll = nil,
		}

		for i = 1, #tbl19 do
			tbl21.Stats[i] = { Hits = 0, Shots = 0 }
		end

		local raycastParams = RaycastParams.new()
		raycastParams.FilterType = Enum.RaycastFilterType.Exclude

		pcall(function()
			raycastParams.RespectCanCollide = true
		end)

		local function slicedfn38()
			return workspace:GetServerTimeNow()
		end

		local function slicedfn39()
			local trigger = tbl21.Trigger
			if trigger and trigger.Parent then
				return trigger
			end
			local reBatSwingTrigger = networking:FindFirstChild("RE/BatSwing/Trigger")
			tbl21.Trigger = reBatSwingTrigger
			return reBatSwingTrigger
		end

		local function slicedfn40(arg)
			return tonumber(arg:GetAttribute("RagdollEndTime")) or 0
		end

		combat.SetLead = function(arg)
			slicedn20 = math.clamp((tonumber(arg) or -275) / 1000, -0.4, 0.1)
		end

		combat.SetSweep = function(arg)
			slicedn21 = math.clamp((tonumber(arg) or 60) / 100, 0, 2.5)
		end

		combat.Ragdolled = function(arg)
			return slicedfn40(arg) > slicedfn38()
		end

		combat.SelfRagdolled = function()
			local sliced13 = slicedfn40(localPlayer)
			if sliced13 <= slicedfn38() then
				return false
			end
			return sliced13 ~= tbl21.SpawnRagdoll
		end

		combat.Humanoid = function(arg)
			if not arg then
				return nil
			end
			local sliced13 = nil

			for _, child in ipairs(arg:GetChildren()) do
				if child:IsA("Humanoid") then
					if child.Health > 0 then
						return child
					end
					sliced13 = sliced13 or child
				end
			end

			return sliced13
		end

		local function slicedfn41(arg)
			local gears = tbl.Gears
			local directory = type(gears) == "table" and gears.Directory or nil
			local flag4 = type(directory) == "table"

			if flag4 then
				flag4 = directory[tostring(arg:GetAttribute("GearName") or arg.Name)]
			end

			flag4 = flag4 or nil
			local batControllerData = type(flag4) == "table" and flag4.BatControllerData or nil
			return type(batControllerData) == "table" and tonumber(batControllerData.RangeBonus) or 0
		end

		combat.Range = function(arg)
			local slicedn31 = workspace:GetAttribute("DragonEggEventActive") == true and 2.5 or 1
			return (slicedn15 + slicedn16 + (arg and slicedfn41(arg) or 0)) * slicedn31
		end

		combat.PickBat = function(arg)
			local tool = arg:FindFirstChildWhichIsA("Tool")
			if tool and tbl4.IsBatTool(tool) then
				return tool
			end
			local sliced13, sliced14, sliced15 = ipairs({ arg, localPlayer:FindFirstChildOfClass("Backpack") })
			local slicedn31 = -1
			local sliced16 = nil

			for _, sliced17 in sliced13, sliced14, sliced15 do
				if sliced17 then
					for _, child in ipairs(sliced17:GetChildren()) do
						if tbl4.IsBatTool(child) then
							local sliced18 = slicedfn41(child)

							if slicedn31 < sliced18 then
								slicedn31 = sliced18
								sliced16 = child
							end
						end
					end
				end
			end

			return sliced16
		end

		local function slicedfn42(parent, arg, arg2)
			if arg2.Parent == parent then
				return true
			end
			local equipAt = tbl21.EquipAt
			if os.clock() - equipAt < 0.2 then
				return false
			end
			tbl21.EquipAt = os.clock()

			pcall(function()
				arg:EquipTool(arg2)
			end)

			if arg2.Parent ~= parent then
				pcall(function()
					arg2.Parent = parent
				end)
			end

			return arg2.Parent == parent
		end

		combat.Parts = function(arg)
			arg = arg and arg.Character
			local humanoidRootPart = arg and arg:FindFirstChild("HumanoidRootPart")
			local humanoid = arg and arg:FindFirstChildOfClass("Humanoid")
			if not humanoidRootPart or not humanoid or humanoid.Health <= 0 then
				return nil, nil
			end
			return arg, humanoidRootPart
		end

		combat.Hittable = function(arg)
			if not arg or arg == localPlayer or arg.Parent ~= Players then
				return false
			end
			local sliced13, sliced14 = combat.Parts(arg)
			if not sliced13 then
				return false
			end

			if sliced13:GetAttribute("IsTrapped") == true or arg:GetAttribute("InBossArena") then
				return false
			end
			return not tbl4.InsideBase(sliced14.Position)
		end

		local function slicedfn43()
			local wallsAt = tbl21.WallsAt
			if os.clock() < wallsAt then
				return tbl21.Walls
			end
			tbl21.WallsAt = os.clock() + 5
			local walls = {}
			local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
			world = world and world:FindFirstChild("Build")

			if world then
				for _, child in ipairs(world:GetChildren()) do
					local collisions = child:FindFirstChild("COLLISIONS")
					collisions = collisions and collisions:FindFirstChild("GUARD NO COLLIDE")

					if collisions then
						for _, child2 in ipairs(collisions:GetChildren()) do
							if tbl20[child2.Name] then
								if child2:IsA("BasePart") then
									table.insert(walls, child2)
								end

								for _, descendant in ipairs(child2:GetDescendants()) do
									if descendant:IsA("BasePart") then
										table.insert(walls, descendant)
									end
								end
							end
						end
					end
				end
			end

			tbl21.Walls = walls
			return walls
		end

		local function slicedfn44(arg)
			if arg.X <= arg.Y and arg.X <= arg.Z then
				return "X", "Y", "Z"
			end

			if arg.Y <= arg.Z then
				return "Y", "X", "Z"
			end
			return "Z", "X", "Y"
		end

		local function slicedfn45(arg)
			local slicedn31 = math.abs(arg.RightVector.Y)
			local slicedn32 = math.abs(arg.UpVector.Y)
			local slicedn33 = math.abs(arg.LookVector.Y)
			if slicedn31 >= slicedn32 and slicedn31 >= slicedn33 then
				return "X"
			end

			if slicedn32 >= slicedn33 then
				return "Y"
			end
			return "Z"
		end

		local function slicedfn46(arg, arg2, arg3, arg4)
			if arg3 == arg4 then
				return true
			end
			local slicedn31 = arg2[arg3] + slicedn28
			return math.abs(arg[arg3]) <= slicedn31
		end

		local function slicedfn47(arg, arg2)
			for _, sliced13 in ipairs(slicedfn43()) do
				if sliced13.Parent then
					local cFrame = sliced13.CFrame
					local size = sliced13.Size
					local sliced14, sliced15, sliced16 = slicedfn44(size)
					local sliced17 = slicedfn45(cFrame)
					local slicedn31 = size / 2
					local sliced18 = cFrame:PointToObjectSpace(arg2)

					if slicedfn46(sliced18, slicedn31, sliced15, sliced17) and slicedfn46(sliced18, slicedn31, sliced16, sliced17) then
						local sliced19 = cFrame:PointToObjectSpace(arg)
						local slicedn32 = math.abs(sliced19[sliced14])
						local slicedn33 = tbl21.WallSide[sliced13]

						if slicedn32 >= slicedn31[sliced14] + slicedn28 * 0.5 or slicedn33 == nil and slicedn32 >= slicedn31[sliced14] then
							slicedn33 = sliced19[sliced14] >= 0 and 1 or -1
							tbl21.WallSide[sliced13] = slicedn33
						elseif slicedn33 == nil then
							slicedn33 = sliced19[sliced14] >= 0 and 1 or -1
						end

						local slicedn34 = slicedn31[sliced14] + slicedn28

						if sliced18[sliced14] * slicedn33 < slicedn34 then
							local tbl22 = { X = sliced18.X, Y = sliced18.Y, Z = sliced18.Z, [sliced14] = slicedn33 * slicedn34 }
							arg2 = cFrame:PointToWorldSpace(Vector3.new(tbl22.X, tbl22.Y, tbl22.Z))
						end
					end
				end
			end

			return arg2
		end

		combat.KeepOffWalls = function(arg, arg2)
			local sliced13 = slicedfn47(arg, arg2)
			local slicedn31 = sliced13 - arg

			if slicedn28 < slicedn31.Magnitude then
				local sliced14 = arg

				for i = 1, 6 do
					local slicedn32 = arg + slicedn31 * (i / slicedn29)
					local sliced15 = slicedfn47(sliced14, slicedn32)
					if (sliced15 - slicedn32).Magnitude > 0.01 then
						return slicedfn47(arg, sliced15)
					end
					sliced14 = sliced15
				end
			end

			return sliced13
		end

		combat.ResetWalls = function()
			table.clear(tbl21.WallSide)
		end

		local slicedn31 = 0
		local sliced13 = nil

		local function slicedfn48(arg)
			local character = localPlayer.Character

			if os.clock() - slicedn31 > 0.5 or character ~= sliced13 then
				slicedn31 = os.clock()
				sliced13 = character
				local filterDescendantsInstances = {}

				for _, player in ipairs(Players:GetPlayers()) do
					if player.Character then
						table.insert(filterDescendantsInstances, player.Character)
					end
				end

				raycastParams.FilterDescendantsInstances = filterDescendantsInstances
			end

			local hit = workspace:Raycast(arg + Vector3.new(0, 60, 0), Vector3.new(0, -400, 0), raycastParams)
			if hit and arg.Y < hit.Position.Y + slicedn30 then
				return Vector3.new(arg.X, hit.Position.Y + slicedn30, arg.Z)
			end
			return arg
		end

		local function slicedfn49(arg, arg2)
			local sliced14 = tbl21.Tracks[arg]

			if not sliced14 then
				local tbl22 = { Samples = {}, Smooth = nil, Heading = nil }
				tbl21.Tracks[arg] = tbl22
				sliced14 = tbl22
			end

			local now = os.clock()
			local samples = sliced14.Samples
			table.insert(samples, { Time = now, Position = arg2.Position })

			while #samples > 2 and now - samples[1].Time > slicedn27 do
				table.remove(samples, 1)
			end

			local assemblyLinearVelocity = arg2.AssemblyLinearVelocity
			local sliced15 = samples[1]
			local slicedn32 = now - sliced15.Time
			local slicedn33

			if slicedn32 >= 0.03 then
				slicedn33 = (arg2.Position - sliced15.Position) / slicedn32

				if not (slicedn33.Magnitude <= 1500 and assemblyLinearVelocity.Magnitude <= slicedn33.Magnitude * 1.4) then
					slicedn33 = assemblyLinearVelocity
				end
			else
				slicedn33 = assemblyLinearVelocity
			end

			local vector = Vector3.new(slicedn33.X, 0, slicedn33.Z)
			sliced14.Smooth = sliced14.Smooth and sliced14.Smooth:Lerp(vector, 0.25) or vector
			local smooth = sliced14.Smooth

			if smooth.Magnitude > 1 then
				local heading = sliced14.Heading and sliced14.Heading:Lerp(smooth.Unit, 0.25) or smooth.Unit
				sliced14.Heading = heading.Magnitude > 0.01 and heading.Unit or smooth.Unit
			end

			return slicedn33, vector, smooth, sliced14
		end

		local function slicedfn50()
			local slicedn32 = 0

			for _, stat in ipairs(tbl21.Stats) do
				slicedn32 += stat.Shots
			end

			local option = tbl21.Option
			local slicedn33 = -math.huge

			for i, stat in ipairs(tbl21.Stats) do
				local slicedn34 = stat.Shots + 1
				local slicedn35 = (stat.Hits + 1) / (stat.Shots + 2) + math.sqrt(2 * math.log(slicedn32 + 2) / slicedn34) * 0.35

				if slicedn35 > slicedn33 then
					slicedn33 = slicedn35
					option = i
				end
			end

			tbl21.Option = option
			return option
		end

		local function slicedfn51()
			local now = os.clock()

			for i = #tbl21.Pending, 1, -1 do
				local sliced14 = tbl21.Pending[i]
				local sliced15 = tbl21.Stats[sliced14.Option]

				if sliced14.RagdollBefore + 0.01 < slicedfn40(sliced14.Target) then
					sliced15.Hits = sliced15.Hits + 1
					sliced15.Shots = sliced15.Shots + 1
					table.remove(tbl21.Pending, i)
				elseif sliced14.Wait < now - sliced14.At then
					if (sliced14.Tool and tonumber(sliced14.Tool:GetAttribute("CooldownEndTime")) or 0) > sliced14.CooldownBefore + 0.01 then
						sliced15.Shots = sliced15.Shots + 1
					end

					table.remove(tbl21.Pending, i)
				end
			end
		end

		combat.Plan = function(arg, arg2, arg3, arg4)
			if not arg3 then
				local sliced14
				sliced14, arg3 = combat.Parts(arg)
			end

			if not arg3 or not arg3.Parent then
				return nil
			end
			local slicedn32 = math.clamp(localPlayer:GetNetworkPing(), 0, 1)
			local slicedn33 = math.clamp(slicedn32 + slicedn17, 0.05, 0.35)
			local sliced14, sliced15, sliced16, sliced17 = slicedfn49(arg or arg3, arg3)
			local sliced18 = slicedfn50()
			local sliced19 = tbl19[sliced18]
			local position = arg3.Position
			local slicedn34 = position + sliced14 * math.max(0, sliced19 + slicedn32 - slicedn33)
			local slicedn35 = position + sliced14 * (sliced19 + slicedn32)
			local magnitude = sliced16.Magnitude
			local heading = sliced17.Heading

			if not heading then
				local vector = Vector3.new(arg2.Position.X - position.X, 0, arg2.Position.Z - position.Z)
				heading = vector.Magnitude > 0.1 and vector.Unit or Vector3.new(0, 0, 1)
			end

			local character = localPlayer.Character
			local sliced20 = combat.Range(character and combat.PickBat(character) or nil)
			local slicedn36 = position + sliced16 * (slicedn32 + sliced19 + slicedn19 + slicedn20) + (magnitude > 1 and sliced16.Unit * slicedn22 * slicedn21 or Vector3.zero)
			local slicedn37 = math.max(5, math.min(sliced20 * 0.7, 6 + magnitude * 0.07)) * slicedn21
			local now = os.clock()
			local slicedn38 = (math.sin(now * 2 * 3.1415926535897931 / slicedn23) * 0.5 + 0.5) * slicedn37
			local slicedn39 = math.sin(now * 2 * 3.1415926535897931 / slicedn24) * slicedn25
			local vector = Vector3.new(-heading.Z, 0, heading.X)

			if vector:Dot(arg2.Position - slicedn36) < 0 then
				vector = -vector
			end

			local slicedn40 = slicedn36 + heading * slicedn38 + vector * (sliced15.Magnitude < slicedn26 and 3 or 1.5) + Vector3.new(0, slicedn39, 0)
			local position2 = arg2.Position

			if not arg4 then
				position2 = combat.KeepOffWalls(arg2.Position, slicedfn48(Vector3.new(slicedn40.X, slicedn40.Y, position.Z)))
			end

			return {
				Goal = position2,
				Velocity = Vector3.new(sliced16.X, 0, sliced16.Z),
				Face = slicedn35,
				Current = slicedn35,
				Historical = slicedn34,
				Option = sliced18,
				Distance = (position - arg2.Position).Magnitude,
			}
		end

		combat.Steer = function(arg, arg2, arg3, arg4, arg5)
			local slicedn32 = math.max(arg5, 0.0041666666666666666)
			local velocity = arg2.Velocity
			local slicedn33 = velocity + (arg2.Goal - arg.Position) / math.max(0.12, slicedn32)
			local slicedn34 = math.min(arg3 + velocity.Magnitude, arg4)

			if slicedn33.Magnitude > slicedn34 then
				slicedn33 = slicedn33.Unit * slicedn34
			end

			local position = arg.Position
			local slicedn35 = position + slicedn33 * slicedn32
			local sliced14 = combat.KeepOffWalls(position, slicedn35)

			if (sliced14 - slicedn35).Magnitude > 0.01 then
				slicedn33 = (sliced14 - position) / slicedn32
			end

			local sliced15 = combat.KeepOffWalls(position, position)

			if (sliced15 - position).Magnitude > 0.01 then
				slicedn33 = (sliced15 - position) / math.max(0.12, slicedn32)
			end

			local assemblyLinearVelocity = slicedn33 + Vector3.new(0, workspace.Gravity * slicedn32 * 0.5, 0)

			pcall(function()
				local vector = Vector3.new(arg2.Face.X - position.X, 0, arg2.Face.Z - position.Z)

				if vector.Magnitude > 0.05 then
					arg.CFrame = CFrame.lookAt(position, position + vector.Unit)
				end

				arg.AssemblyLinearVelocity = assemblyLinearVelocity
				arg.AssemblyAngularVelocity = Vector3.zero
			end)
		end

		combat.TryHit = function(arg, arg2)
			slicedfn51()
			if workspace:GetAttribute("PvPDisabled") == true then
				return "Player hits are off right now"
			end
			local character = localPlayer.Character
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			local sliced14 = combat.Humanoid(character)
			if not humanoidRootPart or not sliced14 or sliced14.Health <= 0 then
				return "Waiting for your character"
			end
			local sliced15 = combat.PickBat(character)
			if not sliced15 then
				return "No bat found"
			end

			if not slicedfn42(character, sliced14, sliced15) then
				return "Equipping " .. tostring(sliced15:GetAttribute("GearName") or sliced15.Name)
			end

			if not combat.Hittable(arg) or combat.Ragdolled(arg) then
				return nil
			end
			arg2 = arg2 or combat.Plan(arg, humanoidRootPart)
			if not arg2 then
				return nil
			end
			local slicedn32 = combat.Range(sliced15) - slicedn18
			local slicedn33 = humanoidRootPart.Position - humanoidRootPart.AssemblyLinearVelocity * slicedn19
			if (arg2.Historical - slicedn33).Magnitude > slicedn32 and (arg2.Current - slicedn33).Magnitude > slicedn32 then
				return nil
			end
			local sliced16 = slicedfn39()
			if not sliced16 then
				return nil
			end
			local slicedn34 = math.clamp(localPlayer:GetNetworkPing(), 0, 1)
			local slicedn35 = tonumber(sliced15:GetAttribute("CooldownEndTime")) or 0
			if slicedfn38() < slicedn35 - slicedn34 * 0.5 then
				return nil
			end
			local lastFire = tbl21.LastFire
			if os.clock() - lastFire < math.max(0.12, slicedn34 * 1.5) then
				return nil
			end
			tbl21.LastFire = os.clock()
			tbl21.Trace = tbl21.Trace + 1

			table.insert(tbl21.Pending, {
				Target = arg,
				Option = arg2.Option,
				At = os.clock(),
				Wait = math.max(0.5, slicedn34 * 2 + 0.3),
				RagdollBefore = slicedfn40(arg),
				CooldownBefore = slicedn35,
				Tool = sliced15,
			})

			local str3 = string.format("%d:%d:%d", localPlayer.UserId, tbl21.Trace, math.floor(slicedfn38() * 1000))

			pcall(function()
				sliced16:FireServer(arg, str3)
			end)

			return "Hitting " .. arg.DisplayName
		end

		combat.ReadyBat = function()
			local character = localPlayer.Character
			local sliced14 = combat.Humanoid(character)
			if not character or not sliced14 or sliced14.Health <= 0 then
				return false
			end
			local sliced15 = combat.PickBat(character)
			return sliced15 ~= nil and slicedfn42(character, sliced14, sliced15)
		end

		combat.Swing = function()
			if tbl4.Steal.Active or tbl4.Steal.Carrying then
				return false
			end
			local lastFire = tbl21.LastFire
			local flag4 = os.clock() - lastFire < 0.3

			if not flag4 then
				flag4 = os.clock() - (tbl21.LastSwing or 0) < 0.15
			end

			if flag4 then
				return false
			end
			local character = localPlayer.Character
			local sliced14 = combat.Humanoid(character)
			if not character or not sliced14 or sliced14.Health <= 0 then
				return false
			end
			local sliced15 = combat.PickBat(character)
			if not sliced15 or not slicedfn42(character, sliced14, sliced15) then
				return false
			end
			tbl21.LastSwing = os.clock()

			pcall(function()
				sliced15:Activate()
			end)

			return true
		end

		combat.HolderOf = function(arg)
			local sliced14 = workspace:FindFirstChild(arg)
			if not sliced14 then
				return nil
			end

			for _, descendant in ipairs(sliced14:GetDescendants()) do
				if descendant:IsA("JointInstance") or descendant:IsA("WeldConstraint") or descendant:IsA("RigidConstraint") then
					local ok, result, result2 = pcall(function()
						return descendant.Part0, descendant.Part1
					end)

					if ok then
						for _, sliced15 in ipairs({ result, result2 }) do
							if typeof(sliced15) == "Instance" and not sliced15:IsDescendantOf(sliced14) then
								local model = sliced15:FindFirstAncestorOfClass("Model")
								local playerFromCharacter = model and (Players:GetPlayerFromCharacter(model) or Players:FindFirstChild(model.Name)) or nil
								if playerFromCharacter and playerFromCharacter ~= localPlayer and playerFromCharacter:IsA("Player") then
									return playerFromCharacter
								end
							end
						end
					end
				end
			end

			return nil
		end

		task.spawn(function()
			while not tbl4.CombatDisposed do
				local holders = {}

				if tbl4.CombatWantsHolders then
					local eggState = tbl.EggState

					if type(eggState) == "table" and type(eggState.ReadFieldEggs) == "function" then
						local ok, result = pcall(eggState.ReadFieldEggs)
						local records = ok and type(result) == "table" and result.Records or nil

						if type(records) == "table" then
							for _, record in pairs(records) do
								if type(record) == "table" and record.State == "Carried" and type(record.Uid) == "string" then
									local sliced14 = combat.HolderOf(record.Uid)

									if sliced14 then
										holders[sliced14] = true
									end
								end
							end
						end
					end
				end

				tbl21.Holders = holders
				task.wait(0.3)
			end
		end)

		combat.IsHolder = function(arg)
			return tbl21.Holders[arg] == true
		end

		local tbl22 = {}

		combat.OnNewLife = function(arg)
			table.insert(tbl22, arg)
		end

		local function slicedfn52()
			table.clear(tbl21.Pending)
			tbl21.LastFire = 0
			tbl21.LastSwing = 0
			tbl21.EquipAt = 0
			table.clear(tbl21.Tracks)
			table.clear(tbl21.WallSide)
			tbl21.SpawnRagdoll = slicedfn40(localPlayer)

			for _, sliced14 in ipairs(tbl22) do
				pcall(sliced14)
			end
		end

		local characterAdded = localPlayer.CharacterAdded
		local connect = characterAdded.Connect
		local tbl23 = { localPlayer.CharacterRemoving:Connect(slicedfn52), connect(characterAdded, slicedfn52) }

		slicedfn4(function()
			tbl4.CombatDisposed = true

			for _, sliced14 in ipairs(tbl23) do
				pcall(function()
					sliced14:Disconnect()
				end)
			end
		end)
	end

	do
		local combat = tbl4.Combat
		local tbl19 = { "Nearest", "Egg Holders", "Specific Player" }
		local slicedn15 = 0.7
		local str3 = "No other players"

		local tbl20 = {
			Handles = {},
			AuraHandle = nil,
			Row = nil,
			Picker = nil,
			TargetMode = tbl19[1],
			Picked = nil,
			LabelToName = {},
			Speed = 400,
			MaxSpeed = 750,
			Target = nil,
			Plan = nil,
			Moving = false,
			Status = "Idle",
			Shown = nil,
			NamesDirty = true,
		}

		local function slicedfn38()
			for i, sliced13 in ipairs(tbl19) do
				if tbl4.Toggle(tbl20.Handles[i], false) then
					return sliced13
				end
			end

			return nil
		end

		local function slicedfn39()
			return tbl4.Toggle(tbl20.AuraHandle, false) == true
		end

		tbl4.CombatActive = function()
			return slicedfn38() ~= nil or slicedfn39()
		end

		local function slicedfn40(arg)
			if not combat.Hittable(arg) then
				return false
			end

			if tbl20.TargetMode == tbl19[2] then
				return combat.IsHolder(arg)
			end

			if tbl20.TargetMode == tbl19[3] then
				return tbl20.Picked ~= nil and arg.Name == tbl20.Picked
			end
			return true
		end

		local function slicedfn41(arg)
			local target = tbl20.Target
			local magnitude

			if target and slicedfn40(target) then
				local sliced13, sliced14 = combat.Parts(target)
				magnitude = (sliced14.Position - arg).Magnitude
			else
				magnitude = math.huge
				target = nil
			end

			local huge = math.huge
			local sliced13 = nil

			for _, player in ipairs(Players:GetPlayers()) do
				if player ~= target and slicedfn40(player) and not combat.Ragdolled(player) then
					local sliced14, sliced15 = combat.Parts(player)
					local magnitude2 = (sliced15.Position - arg).Magnitude

					if magnitude2 < huge then
						huge = magnitude2
						sliced13 = player
					end
				end
			end

			if target then
				if sliced13 and not combat.Ragdolled(target) and huge < magnitude * slicedn15 then
					return sliced13
				end
				return target
			end

			return sliced13
		end

		local function slicedfn42(arg, arg2)
			local sliced13 = nil

			for _, player in ipairs(Players:GetPlayers()) do
				if player ~= localPlayer then
					local character = player.Character
					character = character and character:FindFirstChild("HumanoidRootPart")

					if character then
						local magnitude = (character.Position - arg).Magnitude

						if magnitude < arg2 and combat.Hittable(player) and not combat.Ragdolled(player) then
							arg2 = magnitude
							sliced13 = player
						end
					end
				end
			end

			return sliced13, arg2
		end

		local function slicedfn43()
			tbl20.Plan = nil

			if tbl20.Moving then
				tbl20.Moving = false
				tbl4.EndFlight()
				tbl4.GodMode(false)
				tbl4.Shield("combat", false)
				combat.ResetWalls()
			end

			tbl4.ReleaseMovement("combat")
		end

		combat.OnNewLife(function()
			tbl20.AuraVictim = nil
			tbl20.Target = nil
			tbl20.Plan = nil
			pcall(slicedfn43)
		end)

		local function slicedfn44()
			local movement = tbl4.Movement
			return tbl4.Steal.Active or tbl4.Steal.Carrying or tbl4.Steal.Wanted and tbl4.Toggle(sliced5, false) or movement.Owner ~= nil and movement.Owner ~= "combat" and movement.Owner ~= "treadmill"
		end

		local function slicedfn45(arg)
			local character = localPlayer.Character
			local slicedn16 = combat.Range(character and combat.PickBat(character) or nil) + 6
			local sliced13, sliced14 = slicedfn42(arg.Position, slicedn16 + 24)

			if not sliced13 or sliced14 > slicedn16 then
				tbl20.AuraVictim = nil

				if sliced13 then
					combat.ReadyBat()
				end

				tbl20.Status = "Aura ready, nobody in reach"
				return
			end

			tbl20.AuraVictim = sliced13
			tbl20.Status = combat.TryHit(sliced13, combat.Plan(sliced13, arg, nil, true)) or "Aura on " .. sliced13.DisplayName
		end

		local function slicedfn46()
			local sliced13 = slicedfn38()

			if sliced13 and sliced13 ~= tbl20.TargetMode then
				tbl20.TargetMode = sliced13
				tbl20.Target = nil
			end

			tbl4.CombatWantsHolders = sliced13 == tbl19[2]
			local sliced14 = slicedfn39()
			local flag4 = not sliced13

			if flag4 then
				if tbl20.Target or tbl20.Moving then
					tbl20.Target = nil
					slicedfn43()
				end
			end

			if flag4 and not sliced14 then
				tbl20.Status = "Idle"
				return
			end
			local character = localPlayer.Character
			local humanoidRootPart = character and character:FindFirstChild("HumanoidRootPart")
			local sliced15 = combat.Humanoid(character)

			if not humanoidRootPart or not sliced15 or sliced15.Health <= 0 then
				tbl20.Target = nil
				slicedfn43()
				tbl20.Status = "Waiting for your character"
				return
			end

			if flag4 then
				slicedfn45(humanoidRootPart)
				return
			end
			local sliced16 = slicedfn41(humanoidRootPart.Position)
			tbl20.Target = sliced16

			if not sliced16 then
				slicedfn43()
				if sliced14 then
					slicedfn45(humanoidRootPart)
					return
				end
				tbl20.Status = sliced13 == tbl19[2] and "Waiting for someone to hold an egg" or sliced13 == tbl19[3] and "Picked player is not reachable" or "No player to hit"
				return
			end

			local plan = combat.Plan(sliced16, humanoidRootPart)
			local flag5 = sliced13 ~= tbl19[2]

			if not slicedfn44() and (flag5 or not combat.SelfRagdolled()) and tbl4.ClaimMovement("combat") and not tbl4.AntiGuard.Busy then
				if not tbl20.Moving then
					tbl20.Moving = true
					tbl4.Shield("combat", true)
					tbl4.GodMode(true)
					tbl4.BeginFlight()
				end

				tbl4.GodTick()
				tbl20.Plan = plan
			else
				if tbl20.Moving then
					slicedfn43()
				end

				tbl20.Plan = nil
			end

			local sliced17 = combat.TryHit(sliced16, plan, flag5)
			plan = plan and math.floor(plan.Distance + 0.5) or 0

			if sliced17 then
				tbl20.Status = sliced17 .. string.format("  %d studs", plan)
			elseif slicedfn44() then
				tbl20.Status = string.format("Waiting for Auto Steal, near %s", sliced16.DisplayName)
			else
				tbl20.Status = string.format("Chasing %s  %d studs", sliced16.DisplayName, plan)
			end
		end

		local function slicedfn47()
			local tbl21 = {}

			for _, player in ipairs(Players:GetPlayers()) do
				if player ~= localPlayer then
					table.insert(tbl21, player)
				end
			end

			table.sort(tbl21, function(arg, arg2)
				return string.lower(arg.DisplayName) < string.lower(arg2.DisplayName)
			end)

			local tbl22 = {}

			for _, sliced13 in ipairs(tbl21) do
				tbl22[sliced13.DisplayName] = (tbl22[sliced13.DisplayName] or 0) + 1
			end

			local tbl23 = {}
			local tbl24 = {}

			for _, sliced13 in ipairs(tbl21) do
				local displayName = sliced13.DisplayName

				if tbl22[displayName] > 1 then
					displayName = string.format("%s (@%s)", sliced13.DisplayName, sliced13.Name)
				end

				table.insert(tbl23, displayName)
				tbl24[displayName] = sliced13.Name
			end

			if #tbl23 == 0 then
				tbl23[1] = str3
			end

			return tbl23, tbl24
		end

		local function slicedfn48(arg)
			for k, sliced13 in pairs(tbl20.LabelToName) do
				if sliced13 == arg then
					return k
				end
			end

			return nil
		end

		local connection = RunService.PreSimulation:Connect(function(deltaTime)
			local plan = tbl20.Plan
			if not plan or not tbl20.Moving then
				return
			end
			local sliced13 = tbl4.Root()

			if sliced13 then
				combat.Steer(sliced13, plan, tbl20.Speed, math.max(tbl20.Speed, tbl20.MaxSpeed), deltaTime)
			end
		end)

		local slicedn16 = 0.05
		local slicedn17 = 0

		local connection2 = RunService.Heartbeat:Connect(function()
			local flag4 = slicedfn38() ~= nil
			local sliced13 = slicedfn39()

			if not sliced13 then
				tbl20.AuraVictim = nil
			end

			local now = os.clock()

			if flag4 or not sliced13 or now >= slicedn17 then
				if sliced13 and not flag4 then
					slicedn17 = now + slicedn16
				end

				if not pcall(slicedfn46) then
					tbl20.Status = "Retrying"
				end
			end

			if flag4 or sliced13 and tbl20.AuraVictim ~= nil then
				pcall(combat.Swing)
			end

			local row = tbl20.Row

			if row and tbl20.Shown ~= tbl20.Status and type(row.Set) == "function" then
				tbl20.Shown = tbl20.Status
				pcall(row.Set, row, tbl20.Status)
			end

			local picker = tbl20.Picker

			if tbl20.NamesDirty and picker and type(picker.SetOptions) == "function" then
				tbl20.NamesDirty = false
				local sliced14, sliced15 = slicedfn47()
				tbl20.LabelToName = sliced15
				pcall(picker.SetOptions, picker, sliced14, tbl20.Picked and slicedfn48(tbl20.Picked) or sliced14[1], false)
			end
		end)

		local connection3 = Players.PlayerAdded:Connect(function()
			tbl20.NamesDirty = true
		end)

		local connection4 = Players.PlayerRemoving:Connect(function(player)
			tbl20.NamesDirty = true

			if tbl20.Target == player then
				tbl20.Target = nil
			end
		end)

		slicedfn4(function()
			for _, sliced13 in ipairs({ connection, connection2, connection3, connection4 }) do
				pcall(function()
					sliced13:Disconnect()
				end)
			end

			tbl20.Target = nil
			slicedfn43()
		end)

		local function slicedfn49(arg, arg2)
			if tbl4.Toggle(arg, false) and tbl4.Toggle(tbl4.InvisibilityHandle, false) then
				tbl4.UiDefer(function()
					pcall(arg.Set, arg, false, false)
					tbl4.Notify(arg2, "Turn off Invisibility first, both cannot be on at the same time")
				end)

				return true
			end

			return false
		end

		tbl20.Row = sliced12:CreateText({ Name = "Hit Status", Text = "Idle" })
		local sliced13 = sliced2:CreateExclusiveGroup({ Name = "SourcesHub Combat Targets", MaxActive = 1 })

		for i, sliced14 in ipairs({ "Auto Hit Nearest Player", "Auto Hit Egg Holders", "Auto Hit Specific Player" }) do
			local sliced15 = nil

			sliced15 = sliced12:CreateToggle({
				Name = sliced14,
				Default = false,
				Callback = function()
					slicedfn49(sliced15, sliced14)
				end,
			})

			pcall(sliced15.JoinExclusiveGroup, sliced15, sliced13)
			tbl20.Handles[i] = sliced15
		end

		local sliced14, sliced15 = slicedfn47()
		tbl20.LabelToName = sliced15

		tbl20.Picker = sliced12:CreateDropdown({
			Name = "Hit Player",
			Options = sliced14,
			Default = sliced14[1],
			SubOf = tbl20.Handles[3],
			Callback = function(arg)
				tbl20.Picked = tbl20.LabelToName[tostring(arg)]
				tbl20.Target = nil
			end,
		})

		tbl20.AuraHandle = sliced12:CreateToggle({
			Name = "Hit Aura",
			Default = false,
			Callback = function()
				slicedfn49(tbl20.AuraHandle, "Hit Aura")
			end,
		})

		pcall(tbl20.AuraHandle.JoinExclusiveGroup, tbl20.AuraHandle, sliced13)
		local sliced16 = sliced12:CreateLabel({ Name = "Chase Settings", Text = "Chase Settings" })

		sliced12:CreateSlider({
			Name = "Hit Tween Speed",
			SubOf = sliced16,
			Min = 100,
			Max = 1000,
			Default = 400,
			Increment = 10,
			Unit = "studs/s",
			Callback = function(arg)
				tbl20.Speed = math.clamp(tonumber(arg) or 400, 100, 1000)
			end,
		})

		sliced12:CreateSlider({
			Name = "Hit Max Speed",
			SubOf = sliced16,
			Min = 100,
			Max = 1000,
			Default = 750,
			Increment = 10,
			Unit = "studs/s",
			Callback = function(arg)
				tbl20.MaxSpeed = math.clamp(tonumber(arg) or 750, 100, 1000)
			end,
		})

		sliced12:CreateSlider({
			Name = "Hit Lead",
			SubOf = sliced16,
			Note = "Stand further ahead of the target (+) or closer to them (-)",
			Min = -400,
			Max = 100,
			Default = -275,
			Increment = 1,
			Callback = function(arg)
				combat.SetLead(arg)
			end,
		})

		sliced12:CreateSlider({
			Name = "Hit Sweep",
			SubOf = sliced16,
			Note = "How far you move back and forth in front of the target",
			Min = 0,
			Max = 250,
			Default = 60,
			Increment = 1,
			Unit = "%",
			Callback = function(arg)
				combat.SetSweep(arg)
			end,
		})

		local slicedn18 = 2
		local sliced17 = nil

		local function slicedfn50()
			local getState = sliced2.GetState
			return sliced2:GetState("Quick Pinned Features"), getState(sliced2, "Quick Pin Groups")
		end

		local function slicedfn51()
			local tbl21 = {}

			for _, sliced18 in ipairs({ tbl20.Handles[1], tbl20.Handles[2], tbl20.AuraHandle }) do
				local ok, result = pcall(function()
					return sliced18:GetQuickPath()
				end)

				if ok and type(result) == "string" then
					table.insert(tbl21, result)
				end
			end

			return tbl21
		end

		local function slicedfn52()
			local sliced18, sliced19 = slicedfn50()
			if not sliced18 or not sliced19 then
				return false
			end
			local sliced20 = sliced18:Get()
			local sliced21 = sliced19:Get()
			if type(sliced20) ~= "table" or type(sliced21) ~= "table" then
				return false
			end
			local sliced22 = slicedfn51()
			if #sliced22 == 0 then
				return false
			end

			for _, sliced23 in ipairs(sliced22) do
				if not table.find(sliced20, sliced23) or tonumber(sliced21[sliced23]) ~= slicedn18 then
					return false
				end
			end

			return true
		end

		local function slicedfn53()
			if sliced17 and type(sliced17.SetActionText) == "function" then
				pcall(sliced17.SetActionText, sliced17, slicedfn52() and "Remove" or "Add")
			end
		end

		local function slicedfn54()
			local sliced18, sliced19 = slicedfn50()
			if not sliced18 or not sliced19 then
				tbl4.Notify("Quick Bar", "The Quick Bar is not ready yet, try again in a moment")
				return
			end
			local sliced20 = slicedfn52()
			local tbl21 = {}
			local tbl22 = {}
			local sliced21 = sliced18:Get()

			if type(sliced21) == "table" then
				for i, sliced22 in ipairs(sliced21) do
					tbl21[i] = sliced22
				end
			end

			local sliced22 = sliced19:Get()

			if type(sliced22) == "table" then
				for k, sliced23 in pairs(sliced22) do
					tbl22[k] = sliced23
				end
			end

			for _, sliced23 in ipairs(slicedfn51()) do
				local sliced24 = table.find(tbl21, sliced23)

				if sliced20 then
					if sliced24 then
						table.remove(tbl21, sliced24)
					end

					tbl22[sliced23] = nil
				else
					tbl22[sliced23] = slicedn18

					if not sliced24 then
						table.insert(tbl21, sliced23)
					end
				end
			end

			sliced19:Set(tbl22)
			sliced18:Set(tbl21)
			slicedfn53()
			tbl4.Notify("Quick Bar", sliced20 and "Removed the hit toggles from Quick Bar 2" or "Added the hit toggles to Quick Bar 2")
		end

		sliced17 = sliced12:CreateButton({
			Name = "Add/Remove Hits On Quick Bar 2",
			Note = "Pin or unpin the hit toggles on Quick Bar 2",
			ButtonText = "Add",
			ConfirmText = "Done!",
			Callback = function()
				tbl4.UiDefer(slicedfn54)
			end,
		})

		task.delay(3, function()
			tbl4.UiDefer(slicedfn53)
		end)
	end

	espSection = tbl4.EspSection

	local function slicedfn38(arg, arg2)
		local ok, result = pcall(Font.new, arg, arg2, Enum.FontStyle.Normal)
		return ok and result or nil
	end

	tbl6 = {
		MainFont = slicedfn38("rbxasset://fonts/families/GothamSSm.json", Enum.FontWeight.ExtraBold),
		StatusFont = slicedfn38("rbxasset://fonts/families/FredokaOne.json", Enum.FontWeight.Regular),
		Sequence = function(arg)
			local sliced13 = table.create(#arg)

			for i, sliced14 in ipairs(arg) do
				sliced13[i] = ColorSequenceKeypoint.new(sliced14[1], sliced14[2])
			end

			return ColorSequence.new(sliced13)
		end,
	}

	color = Color3.fromRGB
	sequence = tbl6.Sequence
	palettes = {}

	do
		local gold = {}
		local tbl19 = {}
		local tbl20 = { 0, color(255, 231, 158) }
		local tbl21 = { 0.4, color(255, 196, 66) }
		local tbl22 = { 1, color(214, 142, 12) }
		tbl19[1] = tbl20
		tbl19[2] = tbl21
		tbl19[3] = tbl22
		gold.Text = sequence(tbl19)
		local tbl23 = {}
		local tbl24 = { 0, color(122, 76, 0) }
		local tbl25 = { 0.55, color(62, 38, 0) }
		local tbl26 = { 1, color(20, 12, 0) }
		tbl23[1] = tbl24
		tbl23[2] = tbl25
		tbl23[3] = tbl26
		gold.Stroke = sequence(tbl23)
		gold.Outline = color(255, 232, 152)
		palettes.Gold = gold
	end

	do
		local orange = {}
		local tbl19 = {}
		local tbl20 = { 0, color(255, 198, 132) }
		local tbl21 = { 0.4, color(255, 146, 40) }
		local tbl22 = { 1, color(206, 92, 0) }
		tbl19[1] = tbl20
		tbl19[2] = tbl21
		tbl19[3] = tbl22
		orange.Text = sequence(tbl19)
		local tbl23 = {}
		local tbl24 = { 0, color(112, 54, 0) }
		local tbl25 = { 0.55, color(56, 27, 0) }
		local tbl26 = { 1, color(18, 8, 0) }
		tbl23[1] = tbl24
		tbl23[2] = tbl25
		tbl23[3] = tbl26
		orange.Stroke = sequence(tbl23)
		orange.Outline = color(255, 194, 112)
		palettes.Orange = orange
	end

	do
		local red = {}
		local tbl19 = {}
		local tbl20 = { 0, color(255, 105, 105) }
		local tbl21 = { 0.4, color(255, 28, 40) }
		local tbl22 = { 1, color(184, 0, 18) }
		tbl19[1] = tbl20
		tbl19[2] = tbl21
		tbl19[3] = tbl22
		red.Text = sequence(tbl19)
		local tbl23 = {}
		local tbl24 = { 0, color(124, 0, 15) }
		local tbl25 = { 0.55, color(61, 0, 9) }
		local tbl26 = { 1, color(18, 0, 3) }
		tbl23[1] = tbl24
		tbl23[2] = tbl25
		tbl23[3] = tbl26
		red.Stroke = sequence(tbl23)
		red.Outline = color(255, 128, 138)
		palettes.Red = red
	end
end

local sliced6, sliced7, sliced8, tbl7, tbl8, tbl9, n, paint, bold, color2
local tbl10, id, sliced9, tbl11, tbl12, tbl13, flag, slicedn2, flag2, slicedn3
local flag3, requestEggRefresh, slicedfn8, slicedfn9, slicedfn10, slicedfn11, slicedfn12, slicedfn13, slicedfn14, slicedfn15
local slicedfn16, slicedfn17

do
	do
		do
			local accent = {}
			local tbl14 = {}
			local tbl15 = { 0, color(170, 255, 160) }
			local tbl16 = { 0.45, color(58, 255, 55) }
			local tbl17 = { 1, color(20, 109, 0) }
			tbl14[1] = tbl15
			tbl14[2] = tbl16
			tbl14[3] = tbl17
			accent.Text = sequence(tbl14)
			local tbl18 = {}
			local tbl19 = { 0, color(10, 52, 6) }
			local tbl20 = { 1, color(3, 16, 0) }
			tbl18[1] = tbl19
			tbl18[2] = tbl20
			accent.Stroke = sequence(tbl18)
			accent.Outline = color(58, 255, 55)
			palettes.Accent = accent
		end

		do
			local sheen = {}
			local tbl14 = {}
			local tbl15 = { 0, color(255, 255, 255) }
			local tbl16 = { 0.5, color(222, 222, 222) }
			local tbl17 = { 1, color(255, 255, 255) }
			tbl14[1] = tbl15
			tbl14[2] = tbl16
			tbl14[3] = tbl17
			sheen.Text = sequence(tbl14)
			local tbl18 = {}
			local tbl19 = { 0, color(8, 8, 8) }
			local tbl20 = { 1, color(8, 8, 8) }
			tbl18[1] = tbl19
			tbl18[2] = tbl20
			sheen.Stroke = sequence(tbl18)
			sheen.Outline = color(255, 255, 255)
			palettes.Sheen = sheen
		end

		tbl6.Palettes = palettes

		tbl6.PaletteFromColor = function(arg)
			local color3 = Color3.new(1, 1, 1)
			local color4 = Color3.new(0, 0, 0)
			local tbl14 = {}
			local sequence2 = tbl6.Sequence
			local tbl15 = {}
			local tbl16 = { 0, arg:Lerp(color3, 0.5) }
			local tbl17 = { 0.4, arg:Lerp(color3, 0.1) }
			local tbl18 = { 1, arg:Lerp(color4, 0.25) }
			tbl15[1] = tbl16
			tbl15[2] = tbl17
			tbl15[3] = tbl18
			tbl14.Text = sequence2(tbl15)
			local sequence3 = tbl6.Sequence
			local tbl19 = {}
			local tbl20 = { 0, arg:Lerp(color4, 0.55) }
			local tbl21 = { 0.55, arg:Lerp(color4, 0.75) }
			local tbl22 = { 1, arg:Lerp(color4, 0.92) }
			tbl19[1] = tbl20
			tbl19[2] = tbl21
			tbl19[3] = tbl22
			tbl14.Stroke = sequence3(tbl19)
			tbl14.Outline = arg:Lerp(color3, 0.25)
			return tbl14
		end

		tbl6.SizeScale = 1
		local tbl14 = {}

		tbl6.OnSizeChanged = function(arg)
			table.insert(tbl14, arg)
		end

		tbl6.SetSizeScale = function(sizeScale)
			if tbl6.SizeScale == sizeScale then
				return
			end
			tbl6.SizeScale = sizeScale

			for _, sliced10 in ipairs(tbl14) do
				pcall(sliced10)
			end
		end

		tbl6.RowHeight = function(arg)
			local currentCamera = workspace.CurrentCamera
			return math.max(6, math.floor(math.clamp((currentCamera and currentCamera.ViewportSize.Y or 1080) * 0.014, 13, 19) * (arg or tbl6.SizeScale)))
		end

		tbl6.ScaledWidth = function(arg, arg2)
			return math.max(30, math.floor(arg * (arg2 or tbl6.SizeScale)))
		end

		tbl6.CreateRuntime = function()
			local screenGui = Instance.new("ScreenGui")
			screenGui.Name = slicedfn3()
			screenGui.Archivable = false
			screenGui.ResetOnSpawn = false
			screenGui.IgnoreGuiInset = true
			screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
			screenGui.DisplayOrder = 48
			screenGui.Parent = sliced3
			return screenGui
		end

		tbl6.CreateTag = function(parent, maxDistance)
			local billboardGui = Instance.new("BillboardGui")
			billboardGui.Name = slicedfn3()
			billboardGui.AlwaysOnTop = true
			billboardGui.LightInfluence = 0
			billboardGui.MaxDistance = maxDistance
			local frame = Instance.new("Frame")
			frame.Name = slicedfn3()
			frame.BackgroundTransparency = 1
			frame.BorderSizePixel = 0
			frame.Size = UDim2.fromScale(1, 1)
			frame.Parent = billboardGui
			local uiListLayout = Instance.new("UIListLayout")
			uiListLayout.Name = slicedfn3()
			uiListLayout.FillDirection = Enum.FillDirection.Vertical
			uiListLayout.HorizontalAlignment = Enum.HorizontalAlignment.Center
			uiListLayout.VerticalAlignment = Enum.VerticalAlignment.Center
			uiListLayout.SortOrder = Enum.SortOrder.LayoutOrder
			uiListLayout.Parent = frame
			billboardGui.Parent = parent
			return billboardGui, frame
		end

		tbl6.CreateTextRow = function(parent, fontFace, layoutOrder, arg)
			local frame = Instance.new("Frame")
			frame.Name = slicedfn3()
			frame.BackgroundTransparency = 1
			frame.BorderSizePixel = 0
			frame.Size = UDim2.fromScale(1, arg)
			frame.LayoutOrder = layoutOrder
			frame.Parent = parent

			local function createTextLabel(zIndex)
				local textLabel = Instance.new("TextLabel")
				textLabel.Name = slicedfn3()
				textLabel.BackgroundTransparency = 1
				textLabel.Size = UDim2.fromScale(1, 1)
				textLabel.Text = ""
				textLabel.TextScaled = true
				textLabel.TextStrokeTransparency = 1
				textLabel.TextXAlignment = Enum.TextXAlignment.Center
				textLabel.TextYAlignment = Enum.TextYAlignment.Center
				textLabel.ZIndex = zIndex

				if fontFace then
					textLabel.FontFace = fontFace
				else
					textLabel.Font = Enum.Font.GothamBold
				end

				textLabel.Parent = frame
				return textLabel
			end

			local sliced10 = createTextLabel(2)
			sliced10.Position = UDim2.fromOffset(1, 1)
			sliced10.TextColor3 = Color3.new(0, 0, 0)
			sliced10.TextTransparency = 0.1
			local sliced11 = createTextLabel(3)
			sliced11.TextColor3 = Color3.new(1, 1, 1)
			local uiStroke = Instance.new("UIStroke")
			uiStroke.Name = slicedfn3()
			uiStroke.ApplyStrokeMode = Enum.ApplyStrokeMode.Contextual
			uiStroke.LineJoinMode = Enum.LineJoinMode.Round
			uiStroke.Color = Color3.new(1, 1, 1)
			uiStroke.Transparency = 0.05

			uiStroke.Thickness = pcall(function()
				uiStroke.StrokeSizingMode = Enum.StrokeSizingMode.ScaledSize
			end) and 0.05 or 1.2

			uiStroke.Parent = sliced11
			local uiGradient = Instance.new("UIGradient")
			uiGradient.Name = slicedfn3()
			uiGradient.Rotation = 90
			uiGradient.Parent = uiStroke
			local uiGradient2 = Instance.new("UIGradient")
			uiGradient2.Name = slicedfn3()
			uiGradient2.Rotation = 90
			uiGradient2.Parent = sliced11
			return { Holder = frame, Shadow = sliced10, Label = sliced11, StrokeGradient = uiGradient, TextGradient = uiGradient2, Palette = nil }
		end

		tbl6.SetRow = function(arg, text, palette)
			if arg.Label.Text ~= text then
				arg.Label.Text = text
				arg.Shadow.Text = text
			end

			if arg.Palette ~= palette then
				arg.Palette = palette
				arg.TextGradient.Color = palette.Text
				arg.TextGradient.Rotation = palette.Rotation or 90
				arg.StrokeGradient.Color = palette.Stroke
			end
		end

		tbl6.ReadToggle = function(arg, arg2)
			if type(arg) ~= "table" then
				return arg2 == true
			end

			local ok, result = pcall(function()
				local controller = arg._controller
				return type(controller) == "table" and type(controller.GetValue) == "function" and controller.GetValue()
			end)

			if ok and type(result) == "boolean" then
				return result
			end

			for _, sliced10 in ipairs({ "Get", "GetValue" }) do
				local ok2, result2 = pcall(function()
					return arg[sliced10]
				end)

				if ok2 and type(result2) == "function" then
					local ok3, result3 = pcall(result2, arg)
					if ok3 and type(result3) == "boolean" then
						return result3
					end
				end
			end

			return arg2 == true
		end

		tbl6.SyncSoon = function(arg)
			arg()
			task.delay(0.35, arg)
		end

		tbl6.GetGuardAreas = function()
			local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
			world = world and world:FindFirstChild("Areas")
			return world and world:FindFirstChild("GuardAreas")
		end

		tbl6.FindGuardRoot = function(arg)
			local humanoidRootPart = arg:FindFirstChild("HumanoidRootPart")
			if humanoidRootPart and humanoidRootPart:IsA("BasePart") then
				return humanoidRootPart
			end

			if arg.PrimaryPart then
				return arg.PrimaryPart
			end
			return arg:FindFirstChildWhichIsA("BasePart", true)
		end

		tbl6.WatchGuards = function(arg)
			local tbl15 = {}
			local sliced10 = tbl6.GetGuardAreas()
			if not sliced10 then
				return tbl15
			end

			local function slicedfn18(child)
				local guard = child:FindFirstChild("Guard")

				if guard and guard:IsA("Model") then
					arg(child.Name, guard)
				end

				table.insert(tbl15, child.ChildAdded:Connect(function(child2)
					if child2.Name == "Guard" and child2:IsA("Model") then
						arg(child.Name, child2)
					end
				end))
			end

			for _, child in ipairs(sliced10:GetChildren()) do
				slicedfn18(child)
			end

			table.insert(tbl15, sliced10.ChildAdded:Connect(slicedfn18))
			return tbl15
		end

		tbl6.DisconnectAll = function(arg)
			for _, sliced10 in ipairs(arg) do
				pcall(function()
					sliced10:Disconnect()
				end)
			end

			table.clear(arg)
		end

		local slicedn4 = 18
		local tbl15

		tbl15 = {
			"Icon",
			"Name",
			"Rarity",
			"Mutation",
			"Value",
			"Weight",
			"Size",
			"Sell Price",
			"Distance",
			"Area",
			"State",
		}

		local tbl16 = { "Icon", "Name", "Value" }
		local tbl17 = { "Off", "Rare Only", "All Shown" }
		local tbl18 = { Icon = 3.2, Name = 1.35, Rarity = 1.2, Mutation = 1, Value = 1.1, Info = 1 }
		local sliced10

		local function slicedfn18()
			local ok, result = pcall(Font.new, "rbxassetid://12187365977", Enum.FontWeight.Bold, Enum.FontStyle.Normal)
			return ok and result or tbl6.StatusFont
		end

		sliced10 = slicedfn18()
		local sliced11

		do
			local sequence2 = tbl6.Sequence
			local tbl19 = {}
			local tbl20 = { 0, Color3.fromRGB(255, 255, 255) }
			local tbl21 = { 0.2, Color3.fromRGB(206, 212, 224) }
			local tbl22 = { 0.42, Color3.fromRGB(74, 80, 94) }
			local tbl23 = { 0.58, Color3.fromRGB(42, 46, 56) }
			local tbl24 = { 0.78, Color3.fromRGB(158, 166, 182) }
			local tbl25 = { 1, Color3.fromRGB(250, 252, 255) }
			tbl19[1] = tbl20
			tbl19[2] = tbl21
			tbl19[3] = tbl22
			tbl19[4] = tbl23
			tbl19[5] = tbl24
			tbl19[6] = tbl25
			sliced11 = sequence2(tbl19)
		end

		local sliced12 = tbl6.PaletteFromColor(Color3.fromRGB(77, 255, 122))
		local tbl19 = {}

		do
			local sequence2 = tbl6.Sequence
			local tbl20 = {}
			local tbl21 = { 0, Color3.fromRGB(255, 255, 255) }
			local tbl22 = { 0.5, Color3.fromRGB(222, 238, 255) }
			local tbl23 = { 1, Color3.fromRGB(255, 255, 255) }
			tbl20[1] = tbl21
			tbl20[2] = tbl22
			tbl20[3] = tbl23
			tbl19.Text = sequence2(tbl20)
		end

		do
			local sequence2 = tbl6.Sequence
			local tbl20 = {}
			local tbl21 = { 0, Color3.fromRGB(8, 8, 8) }
			local tbl22 = { 1, Color3.fromRGB(8, 8, 8) }
			tbl20[1] = tbl21
			tbl20[2] = tbl22
			tbl19.Stroke = sequence2(tbl20)
		end

		tbl19.Outline = Color3.fromRGB(255, 255, 255)
		local slicedn5 = 0.8
		local slicedn6 = 4.5
		local slicedn7 = 20
		local slicedn8 = 0.002
		local tbl20 = { Golden = tbl6.Palettes.Gold }

		do
			local silver = {}
			local sequence2 = tbl6.Sequence
			local tbl21 = {}
			local tbl22 = { 0, Color3.fromRGB(255, 255, 255) }
			local tbl23 = { 0.45, Color3.fromRGB(214, 222, 232) }
			local tbl24 = { 1, Color3.fromRGB(150, 160, 175) }
			tbl21[1] = tbl22
			tbl21[2] = tbl23
			tbl21[3] = tbl24
			silver.Text = sequence2(tbl21)
			local sequence3 = tbl6.Sequence
			local tbl25 = {}
			local tbl26 = { 0, Color3.fromRGB(60, 66, 78) }
			local tbl27 = { 0.55, Color3.fromRGB(30, 33, 40) }
			local tbl28 = { 1, Color3.fromRGB(10, 11, 14) }
			tbl25[1] = tbl26
			tbl25[2] = tbl27
			tbl25[3] = tbl28
			silver.Stroke = sequence3(tbl25)
			silver.Outline = Color3.fromRGB(214, 222, 232)
			tbl20.Silver = silver
		end

		tbl20.Sakura = tbl6.PaletteFromColor(Color3.fromRGB(255, 158, 216))
		tbl20.GreatBloom = tbl6.PaletteFromColor(Color3.fromRGB(124, 255, 196))
		tbl20.Boss = tbl6.PaletteFromColor(Color3.fromRGB(255, 122, 122))
		tbl20.Monstrous = tbl6.PaletteFromColor(Color3.fromRGB(192, 139, 255))

		do
			local rainbow = {}
			local sequence2 = tbl6.Sequence
			local tbl21 = {}
			local tbl22 = { 0, Color3.fromRGB(255, 107, 107) }
			local tbl23 = { 0.2, Color3.fromRGB(255, 179, 107) }
			local tbl24 = { 0.4, Color3.fromRGB(255, 240, 107) }
			local tbl25 = { 0.6, Color3.fromRGB(107, 255, 138) }
			local tbl26 = { 0.8, Color3.fromRGB(107, 200, 255) }
			local tbl27 = { 1, Color3.fromRGB(185, 107, 255) }
			tbl21[1] = tbl22
			tbl21[2] = tbl23
			tbl21[3] = tbl24
			tbl21[4] = tbl25
			tbl21[5] = tbl26
			tbl21[6] = tbl27
			rainbow.Text = sequence2(tbl21)
			local sequence3 = tbl6.Sequence
			local tbl28 = {}
			local tbl29 = { 0, Color3.fromRGB(20, 20, 30) }
			local tbl30 = { 1, Color3.fromRGB(8, 8, 12) }
			tbl28[1] = tbl29
			tbl28[2] = tbl30
			rainbow.Stroke = sequence3(tbl28)
			rainbow.Outline = Color3.fromRGB(255, 255, 255)
			rainbow.Rotation = 0
			tbl20.Rainbow = rainbow
		end

		local sliced13 = tbl6.PaletteFromColor(Color3.fromRGB(143, 227, 255))
		local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")
		local slicedn9 = 0
		local tbl21

		tbl21 = {
			Eggs = false,
			MinRarity = 5,
			Specific = {},
			MutationSet = {},
			AnyMutation = false,
			NoMutation = false,
			Info = {},
			Highlight = tbl17[1],
			MinValue = 0,
			HighlightMin = 6,
			MaxDistance = math.huge,
			SizeScale = 0.75,
			FixedSize = false,
			OwnBase = true,
		}

		for _, sliced14 in ipairs(tbl16) do
			tbl21.Info[sliced14] = true
		end

		local tbl22 = {}
		local tbl23, sliced14, flag4, slicedn10, slicedn11, flag5, sliced15, slicedn12, slicedfn19
		local tbl24 = {}
		tbl23 = {}
		sliced14 = nil
		flag4 = false
		slicedn10 = 0
		slicedn11 = 0
		flag5 = false
		sliced15 = nil
		slicedn12 = 0

		slicedfn19 = function(arg)
			local sliced16 = tbl24[arg]
			if sliced16 then
				return sliced16
			end
			local directory = tbl.Assets and tbl.Assets.Directory
			local flag6 = type(directory) == "table" and directory[arg]
			local rarity = type(flag6) == "table" and type(flag6.Rarity) == "table" and flag6.Rarity or nil
			local color3 = rarity and typeof(rarity.Color) == "Color3" and rarity.Color or Color3.new(1, 1, 1)
			local sliced17 = tbl6.PaletteFromColor(color3)
			local rarityGradient = rarity and rarity.RarityGradient

			if rarity and typeof(rarityGradient) ~= "Instance" then
				local assets = ReplicatedStorage:FindFirstChild("Assets")
				assets = assets and assets:FindFirstChild("UI")
				assets = assets and assets:FindFirstChild("RarityGradients")

				if assets then
					assets = assets:FindFirstChild(tostring(rarity._id or rarity.DisplayName or ""))
				end

				rarityGradient = assets and assets:FindFirstChild("RarityGradient") or nil
			end

			if typeof(rarityGradient) == "Instance" and rarityGradient:IsA("UIGradient") then
				sliced17.Text = rarityGradient.Color
				sliced17.Rotation = rarityGradient.Rotation
			end

			local name

			if rarity then
				name = tostring(rarity.DisplayName or rarity._id or "")
			else
				name = rarity
			end

			name = name or ""
			local rarityPalette

			if string.upper(name) ~= "SECRET" then
				rarityPalette = sliced17
			else
				rarityPalette = { Text = sliced11, Stroke = sliced17.Stroke, Outline = sliced17.Outline, Rotation = 90 }
			end

			local tbl25 = {}
			local number

			if rarity then
				number = tonumber(rarity.RarityNumber or rarity.Rank)
			else
				number = rarity
			end

			tbl25.Number = number or 0
			tbl25.Name = name
			tbl25.Color = color3
			tbl25.Palette = sliced17
			tbl25.RarityPalette = rarityPalette
			local displayName = type(flag6) == "table"

			if displayName then
				displayName = tostring(flag6.DisplayName or arg)
			end

			tbl25.DisplayName = displayName or tostring(arg)
			tbl25.Icon = type(flag6) == "table" and flag6.Icon or nil
			tbl25.EarningRate = type(flag6) == "table" and tonumber(flag6.EarningRate) or 0
			tbl24[arg] = tbl25
			return tbl25
		end

		local slicedfn20, slicedfn21, slicedfn22, tbl25, slicedfn23

		do
			local function slicedfn24(arg)
				local areaEggSlotsClient = workspace:FindFirstChild("AreaEggSlotsClient")
				areaEggSlotsClient = areaEggSlotsClient and areaEggSlotsClient:FindFirstChild(arg)
				if areaEggSlotsClient and areaEggSlotsClient:IsA("Model") then
					local hitbox = areaEggSlotsClient:FindFirstChild("Hitbox")
					return areaEggSlotsClient, hitbox and hitbox:IsA("BasePart") and hitbox or nil
				end
				return nil, nil
			end

			local function slicedfn25()
				if not sliced15 or not sliced15.Parent then
					sliced15 = tbl6.CreateRuntime()
				end
			end

			local function slicedfn26(arg)
				local slicedn13 = tonumber(arg) or 0
				local tbl26 = { "", "K", "M", "B", "T", "Qa", "Qi" }
				local slicedn14 = 1

				while math.abs(slicedn13) >= 1000 and slicedn14 < #tbl26 do
					slicedn13 /= 1000
					slicedn14 += 1
				end

				return string.format(slicedn14 == 1 and "%.0f%s" or "%.2f%s", slicedn13, tbl26[slicedn14])
			end

			local function slicedfn27(arg)
				local currentCamera = workspace.CurrentCamera
				if not currentCamera then
					return tbl21.MaxDistance
				end
				return math.min(tbl21.MaxDistance, arg * currentCamera.ViewportSize.Y / (2 * slicedn7 * math.tan(math.rad(currentCamera.FieldOfView) * 0.5)))
			end

			local function slicedfn28(arg)
				local tbl26 = {
					{ arg.IconHolder, tbl18.Icon, arg.ShowIcon },
					{ arg.NameRow.Holder, tbl18.Name, arg.ShowName },
					{ arg.RarityRow.Holder, tbl18.Rarity, arg.ShowRarity },
					{ arg.MutationRow.Holder, tbl18.Mutation, arg.ShowMutation },
					{ arg.ValueRow.Holder, tbl18.Value, arg.ShowValue },
					{ arg.ExtraRow.Holder, tbl18.Info, arg.ShowExtra },
				}

				local slicedn13 = 0

				for _, sliced16 in ipairs(tbl26) do
					if sliced16[3] then
						slicedn13 += sliced16[2]
					end
				end

				local slicedn14 = math.max(slicedn13, 1)

				for _, sliced16 in ipairs(tbl26) do
					sliced16[1].Visible = sliced16[3]
					sliced16[1].Size = UDim2.fromScale(1, sliced16[3] and sliced16[2] / slicedn14 or 0)
				end

				local sliced16 = tbl6.ScaledWidth(120, tbl21.SizeScale)
				local height = math.max(1, math.floor(tbl6.RowHeight(tbl21.SizeScale) * slicedn14))

				if arg.Width ~= sliced16 or arg.Height ~= height or arg.Fixed ~= tbl21.FixedSize then
					arg.Width = sliced16
					arg.Height = height
					arg.Fixed = tbl21.FixedSize

					if tbl21.FixedSize then
						local slicedn15 = slicedn6 * tbl21.SizeScale
						arg.Billboard.Size = UDim2.fromScale(slicedn15, slicedn15 * height / sliced16)
						arg.Billboard.MaxDistance = slicedfn27(slicedn15)
					else
						arg.Billboard.Size = UDim2.fromOffset(sliced16, height)
						arg.Billboard.MaxDistance = tbl21.MaxDistance
					end
				end
			end

			slicedfn20 = function(arg)
				arg.Width = nil
				slicedfn28(arg)
			end

			local function slicedfn29()
				local sliced16, sliced17 = tbl6.CreateTag(sliced15, tbl21.MaxDistance)
				local frame = Instance.new("Frame")
				frame.Name = slicedfn3()
				frame.BackgroundTransparency = 1
				frame.BorderSizePixel = 0
				frame.LayoutOrder = 0
				frame.Parent = sliced17
				local imageLabel = Instance.new("ImageLabel")
				imageLabel.Name = slicedfn3()
				imageLabel.AnchorPoint = Vector2.new(0.5, 1)
				imageLabel.BackgroundTransparency = 1
				imageLabel.Position = UDim2.fromScale(0.5, 1)
				imageLabel.Size = UDim2.fromScale(1, 1)
				imageLabel.ScaleType = Enum.ScaleType.Fit
				imageLabel.Parent = frame
				local uiAspectRatioConstraint = Instance.new("UIAspectRatioConstraint")
				uiAspectRatioConstraint.Name = slicedfn3()
				uiAspectRatioConstraint.AspectRatio = 1
				uiAspectRatioConstraint.DominantAxis = Enum.DominantAxis.Height
				uiAspectRatioConstraint.Parent = imageLabel

				local tbl26 = {
					Billboard = sliced16,
					IconHolder = frame,
					Icon = imageLabel,
					NameRow = tbl6.CreateTextRow(sliced17, tbl6.MainFont, 1, 0.4),
					RarityRow = tbl6.CreateTextRow(sliced17, sliced10, 2, 0.2),
					MutationRow = tbl6.CreateTextRow(sliced17, tbl6.MainFont, 3, 0.2),
					ValueRow = tbl6.CreateTextRow(sliced17, tbl6.MainFont, 4, 0.2),
					ExtraRow = tbl6.CreateTextRow(sliced17, tbl6.MainFont, 5, 0.2),
					Highlight = nil,
					Anchor = nil,
					CFrame = nil,
					Width = nil,
					Height = nil,
					ShowIcon = false,
					ShowName = true,
					ShowRarity = false,
					ShowMutation = false,
					ShowValue = false,
					ShowExtra = false,
				}

				slicedfn28(tbl26)
				return tbl26
			end

			local function slicedfn30(arg)
				if arg.Highlight then
					arg.Highlight:Destroy()
					arg.Highlight = nil
					slicedn12 -= 1
				end
			end

			local function slicedfn31(arg, arg2)
				local slicedn13 = tonumber(arg.AssetScale) or 1
				local slicedn14 = slicedn13 > 5 and (slicedn13 / 5) ^ 1.2 * 19.637875755794113 or slicedn13 ^ 1.85
				local mutations = tbl.Mutations
				local flag6 = type(mutations) == "table" and type(mutations.EarningsFor) == "function"
				local slicedn15 = 1

				if flag6 then
					local ok, result = pcall(mutations.EarningsFor, type(arg.Mutations) == "table" and arg.Mutations or {})
					local flag7 = ok and type(result) == "number"
					local slicedn16 = 1

					if flag7 then
						slicedn15 = result
					else
						slicedn15 = slicedn16
					end
				end

				return arg2.EarningRate * slicedn14 * slicedn15
			end

			local function slicedfn32()
				local tbl26 = {}
				local eggState = tbl.EggState
				local placedEggRenders = workspace:FindFirstChild("PlacedEggRenders")
				if not placedEggRenders or type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
					return tbl26
				end
				local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
				if not ok or type(result) ~= "table" then
					return tbl26
				end
				local str = tostring(localPlayer.UserId)
				local tbl27 = {}

				for _, child in ipairs(placedEggRenders:GetChildren()) do
					if string.find(child.Name, str, 1, true) then
						tbl27[#tbl27 + 1] = child
					end
				end

				for k, sliced16 in pairs(result) do
					if type(sliced16) == "table" and sliced16.Placement ~= nil and type(sliced16.AssetCategory) == "string" then
						local base = tostring(k)
						local sliced17 = nil

						for _, sliced18 in ipairs(tbl27) do
							if sliced18.Name == base or string.find(sliced18.Name, base, 1, true) or sliced18:GetAttribute("Uid") == base then
								sliced17 = sliced18
								break
							end
						end

						if sliced17 then
							local ok2, result2 = pcall(function()
								return sliced17:IsA("Model") and sliced17:GetPivot() or sliced17.CFrame
							end)

							local mutations = type(sliced16.Mutations) == "table" and sliced16.Mutations or {}

							tbl26[#tbl26 + 1] = {
								Uid = "base:" .. base,
								AssetCategory = sliced16.AssetCategory,
								AssetScale = sliced16.AssetScale,
								Mutations = mutations,
								BaseMutation = sliced16.BaseMutation or mutations[1],
								State = "Base",
								AreaId = "Your Base",
								BottomCFrame = ok2 and result2 or nil,
								Model = sliced17,
							}
						end
					end
				end

				return tbl26
			end

			local function slicedfn33(arg, arg2)
				if arg.State == "Claimed" then
					return false
				end

				if tbl21.MinRarity > 0 and arg2.Number < tbl21.MinRarity then
					return false
				end
				local flag6 = tbl21.MinValue > 0

				if flag6 then
					local minValue = tbl21.MinValue
					flag6 = slicedfn31(arg, arg2) < minValue
				end

				if flag6 then
					return false
				end
				return true
			end

			local function slicedfn34(arg, arg2, arg3)
				local model, hitbox

				if typeof(arg2.Model) == "Instance" then
					model = arg2.Model
					hitbox = model:FindFirstChild("Hitbox", true) or model:FindFirstChildWhichIsA("BasePart", true)
					hitbox = hitbox and hitbox:IsA("BasePart") and hitbox or nil
				else
					model, hitbox = slicedfn24(arg2.Uid)
				end

				local bottomCFrame = arg2.BottomCFrame

				if typeof(bottomCFrame) == "CFrame" then
					local terrain = hitbox or workspace.Terrain

					if arg.Anchor ~= terrain or arg.CFrame ~= bottomCFrame then
						arg.Anchor = terrain
						arg.CFrame = bottomCFrame
						arg.Billboard.Adornee = terrain
						arg.Billboard.StudsOffsetWorldSpace = bottomCFrame.Position - terrain.Position + Vector3.new(0, (hitbox and hitbox.Position.Y - bottomCFrame.Position.Y or 1) + slicedn5, 0)
					end
				end

				local info = tbl21.Info
				local baseMutation = arg2.BaseMutation
				local showMutation = type(baseMutation) == "string" and baseMutation ~= ""
				local slicedn13 = tonumber(arg2.AssetScale) or 1
				local showIcon = info.Icon == true and arg3.Icon ~= nil

				if showIcon and arg.Icon.Image ~= tostring(arg3.Icon) then
					arg.Icon.Image = tostring(arg3.Icon)
				end

				local showName = info.Name == true

				if showName then
					tbl6.SetRow(arg.NameRow, arg3.DisplayName, tbl19)
				end

				local showRarity = info.Rarity == true and arg3.Name ~= ""

				if showRarity then
					local rarityPalette = arg3.RarityPalette
					tbl6.SetRow(arg.RarityRow, string.upper(arg3.Name), rarityPalette)
				end

				showMutation = info.Mutation == true and showMutation

				if showMutation then
					tbl6.SetRow(arg.MutationRow, string.upper(slicedfn7(baseMutation)), tbl20[baseMutation] or sliced13)
				end

				local showValue = info.Value == true

				if showValue then
					tbl6.SetRow(arg.ValueRow, "$" .. slicedfn26(slicedfn31(arg2, arg3)) .. "/s", sliced12)
				end

				local tbl26 = {}
				local eggRecords = tbl.EggRecords

				if info.Weight and type(eggRecords) == "table" and type(eggRecords.WeightKgForScale) == "function" then
					local ok, result = pcall(eggRecords.WeightKgForScale, arg2.AssetCategory, slicedn13)

					if ok and tonumber(result) then
						table.insert(tbl26, slicedfn26(result) .. " kg")
					end
				end

				if info.Size then
					table.insert(tbl26, string.format("x%.2f", slicedn13))
				end

				if info["Sell Price"] and type(eggRecords) == "table" and type(eggRecords.SellPrice) == "function" then
					local ok, result = pcall(eggRecords.SellPrice, arg2)

					if ok and tonumber(result) then
						table.insert(tbl26, "$" .. slicedfn26(result))
					end
				end

				if info.Distance and typeof(bottomCFrame) == "CFrame" then
					local character = localPlayer.Character
					character = character and character:FindFirstChild("HumanoidRootPart")

					if character then
						table.insert(tbl26, string.format("%dm", math.floor((character.Position - bottomCFrame.Position).Magnitude + 0.5)))
					end
				end

				if info.Area and arg2.AreaId ~= nil then
					table.insert(tbl26, tostring(arg2.AreaId))
				end

				if info.State and arg2.State ~= nil and arg2.State ~= "Slot" then
					table.insert(tbl26, tostring(arg2.State))
				end

				local showExtra = #tbl26 > 0

				if showExtra then
					tbl6.SetRow(arg.ExtraRow, table.concat(tbl26, "  |  "), tbl6.Palettes.Sheen)
				end

				if arg.ShowIcon ~= showIcon or arg.ShowName ~= showName or arg.ShowRarity ~= showRarity or arg.ShowMutation ~= showMutation or arg.ShowValue ~= showValue or arg.ShowExtra ~= showExtra then
					arg.ShowIcon = showIcon
					arg.ShowName = showName
					arg.ShowRarity = showRarity
					arg.ShowMutation = showMutation
					arg.ShowValue = showValue
					arg.ShowExtra = showExtra
					slicedfn28(arg)
				end

				if (tbl21.Highlight == tbl17[3] or tbl21.Highlight == tbl17[2] and arg3.Number >= tbl21.HighlightMin) and model then
					if not arg.Highlight and slicedn12 < slicedn4 then
						local highlight = Instance.new("Highlight")
						highlight.Name = slicedfn3()
						highlight.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
						highlight.FillTransparency = 0.82
						highlight.OutlineTransparency = 0.05
						highlight.FillColor = arg3.Color
						highlight.OutlineColor = arg3.Palette.Outline
						highlight.Parent = sliced15
						arg.Highlight = highlight
						slicedn12 += 1
					end

					if arg.Highlight and arg.Highlight.Adornee ~= model then
						arg.Highlight.Adornee = model
					end
				else
					slicedfn30(arg)
				end
			end

			local function slicedfn35(arg)
				slicedfn30(arg)
				arg.Billboard:Destroy()
			end

			local function slicedfn36()
				local sliced16 = tbl22
				local sliced17 = sliced15
				tbl22 = {}
				sliced15 = nil
				slicedn12 = 0

				task.spawn(function()
					local now = os.clock()

					for _, sliced18 in pairs(sliced16) do
						if sliced18.Highlight then
							sliced18.Highlight:Destroy()
						end

						sliced18.Billboard:Destroy()

						if slicedn8 < os.clock() - now then
							RunService.Heartbeat:Wait()
							now = os.clock()
						end
					end

					if sliced17 then
						sliced17:Destroy()
					end
				end)
			end

			local function slicedfn37(arg, arg2, arg3)
				local function slicedfn38()
					return arg2 == slicedn11 and arg3 == slicedn10 and flag4
				end

				slicedfn25()
				local tbl26 = {}
				local now = os.clock()

				for _, sliced16 in pairs(arg) do
					local uid = type(sliced16) == "table" and sliced16.Uid

					if type(uid) == "string" and type(sliced16.AssetCategory) == "string" then
						local sliced17 = slicedfn19(sliced16.AssetCategory)

						if tbl21.Eggs and slicedfn33(sliced16, sliced17) then
							tbl26[uid] = true
							local sliced18 = tbl22[uid]

							if not sliced18 then
								sliced18 = slicedfn29()
								tbl22[uid] = sliced18
							end

							slicedfn34(sliced18, sliced16, sliced17)
						end
					end

					if not (slicedn8 < os.clock() - now) then
						continue
					end
					RunService.Heartbeat:Wait()
					now = os.clock()
					if not slicedfn38() then
						return
					end
				end

				if tbl21.Eggs and tbl21.OwnBase then
					for _, sliced16 in ipairs(slicedfn32()) do
						local sliced17 = slicedfn19(sliced16.AssetCategory)

						if slicedfn33(sliced16, sliced17) then
							tbl26[sliced16.Uid] = true
							local sliced18 = tbl22[sliced16.Uid]

							if not sliced18 then
								sliced18 = slicedfn29()
								tbl22[sliced16.Uid] = sliced18
							end

							slicedfn34(sliced18, sliced16, sliced17)
						end
					end
				end

				for k, sliced16 in pairs(tbl22) do
					if not tbl26[k] then
						tbl22[k] = nil
						slicedfn35(sliced16)
					end
				end

				return true
			end

			local flag6 = false
			local flag7 = false

			slicedfn21 = function()
				if not flag4 or not sliced14 then
					return
				end
				flag6 = true
				if flag7 then
					return
				end
				flag7 = true

				task.defer(function()
					while flag4 and sliced14 and flag6 do
						flag6 = false
						slicedn11 += 1
						local ok, result = pcall(slicedfn37, sliced14, slicedn11, slicedn10)

						if ok and result ~= true then
							flag6 = true
						end

						RunService.Heartbeat:Wait()
					end

					flag7 = false
				end)
			end

			local function slicedfn38()
				local sliced16 = slicedn10

				if sliced14 and next(tbl22) == nil then
					slicedfn21()
				end

				local eggState = tbl.EggState
				local flag8 = type(eggState) == "table" and type(eggState.ReadFieldEggs) == "function"
				local records = nil

				if flag8 then
					local ok, result = pcall(eggState.ReadFieldEggs)
					ok = ok and type(result) == "table" and type(result.Records) == "table"
					records = nil

					if ok then
						records = result.Records
					end
				end

				if records == nil and rfEggWorldAskFieldEggSnapshot and os.clock() >= slicedn9 then
					slicedn9 = os.clock() + 30
					local ok, result = pcall(rfEggWorldAskFieldEggSnapshot.InvokeServer, rfEggWorldAskFieldEggSnapshot)

					if ok and type(result) == "table" and type(result.Records) == "table" then
						records = result.Records
					end
				end

				if sliced16 ~= slicedn10 or not flag4 then
					return
				end

				if records ~= nil then
					local tbl26 = {}

					for k, record in pairs(records) do
						tbl26[k] = record
					end

					sliced14 = tbl26
				end

				if sliced14 then
					slicedfn21()
				end
			end

			local function slicedfn39()
				task.spawn(pcall, slicedfn38)
			end

			local function slicedfn40()
				if flag5 then
					return
				end
				flag5 = true

				task.delay(0.5, function()
					flag5 = false

					if flag4 then
						slicedfn39()
					end
				end)
			end

			slicedfn22 = function()
				for _, sliced16 in pairs(tbl22) do
					slicedfn20(sliced16)
				end
			end

			local function slicedfn41()
				flag4 = false
				slicedn10 += 1
				slicedn11 += 1
				tbl6.DisconnectAll(tbl23)
				slicedfn36()
			end

			local function slicedfn42()
				if flag4 then
					slicedfn39()
					return
				end
				flag4 = true
				local sliced16 = slicedn10
				local eggState = tbl.EggState

				if type(eggState) == "table" then
					for _, sliced17 in ipairs({ "FieldRefreshed", "FieldShifted", "FieldGone", "FieldClaimed", "SnapshotRefreshed" }) do
						local sliced18 = eggState[sliced17]

						if type(sliced18) == "table" and type(sliced18.Connect) == "function" then
							local ok, result = pcall(sliced18.Connect, sliced18, slicedfn40)

							if ok and result then
								table.insert(tbl23, result)
							end
						end
					end
				end

				for _, sliced17 in ipairs({ "AreaEggSlotsClient", "PlacedEggRenders" }) do
					local sliced18 = workspace:FindFirstChild(sliced17)

					if sliced18 then
						table.insert(tbl23, sliced18.ChildAdded:Connect(slicedfn40))
						table.insert(tbl23, sliced18.ChildRemoved:Connect(slicedfn40))
					end
				end

				task.spawn(function()
					while sliced16 == slicedn10 do
						task.wait(10)
						if sliced16 == slicedn10 then
							slicedfn40()
							continue
						end
						break
					end
				end)

				task.spawn(function()
					while sliced16 == slicedn10 do
						task.wait(1)

						if sliced16 == slicedn10 then
							if tbl21.Info.Distance then
								slicedfn21()
							end

							continue
						end

						break
					end
				end)

				slicedfn39()
			end

			local function slicedfn43()
				if tbl21.Eggs then
					slicedfn42()
				else
					slicedfn41()
				end
			end

			tbl25 = { Eggs = nil }
			local tbl26 = { Eggs = false }
			local flag8 = false

			local function slicedfn44()
				if flag8 then
					return
				end
				local sliced16 = tbl6.ReadToggle(tbl25.Eggs, tbl26.Eggs)
				if sliced16 == tbl21.Eggs and flag4 == sliced16 then
					return
				end
				tbl21.Eggs = sliced16
				slicedfn43()
			end

			slicedfn4(function()
				flag8 = true
				tbl21.Eggs = false
				slicedfn41()
			end)

			slicedfn23 = function(arg)
				local tbl27 = {}

				if type(arg) == "table" then
					for k, sliced16 in pairs(arg) do
						k = sliced16 == true and type(k) == "string" and k
						local flag9

						if k then
							flag9 = k
						else
							flag9 = type(sliced16) == "string" and sliced16
						end

						flag9 = flag9 or nil

						if flag9 then
							tbl27[flag9] = true
						end
					end
				end

				return tbl27
			end

			tbl25.Eggs = espSection:CreateToggle({
				Name = "ESP Eggs",
				Default = false,
				Callback = function(arg)
					tbl26.Eggs = arg == true
					tbl6.SyncSoon(slicedfn44)
				end,
			})
		end

		espSection:CreateToggle({
			Name = "ESP Fixed Size",
			Default = false,
			SubOf = tbl25.Eggs,
			Callback = function(arg)
				local fixedSize = arg == true

				if tbl21.FixedSize ~= fixedSize then
					tbl21.FixedSize = fixedSize
					slicedfn22()
				end
			end,
		})

		espSection:CreateToggle({
			Name = "ESP Own Base Eggs",
			Note = "Also show the eggs placed in your own base",
			Default = true,
			SubOf = tbl25.Eggs,
			Callback = function(arg)
				tbl21.OwnBase = arg ~= false
				slicedfn21()
			end,
		})

		do
			local tbl26 = { "Any" }
			local tbl27 = { Any = 0 }
			local tbl28 = {}
			local tbl29 = {}
			local tbl30 = { "Any Mutation", "No Mutation" }
			local directory = tbl.Assets and tbl.Assets.Directory
			local tbl31 = {}
			local tbl32 = {}

			if type(directory) == "table" then
				for k, sliced16 in pairs(directory) do
					local rarity = type(sliced16) == "table" and sliced16.Rarity or nil
					local flag6 = type(rarity) == "table"

					if flag6 then
						flag6 = tonumber(rarity.RarityNumber or rarity.Rank)
					end

					flag6 = flag6 or nil

					if flag6 then
						local str = tostring(rarity.DisplayName or rarity._id or flag6)
						tbl31[flag6] = tbl31[flag6] or str

						table.insert(tbl32, {
							Category = tostring(k),
							Name = tostring(sliced16.DisplayName or k),
							Rarity = flag6,
							RarityName = str,
						})
					end
				end
			end

			local tbl33 = {}

			for k in pairs(tbl31) do
				table.insert(tbl33, k)
			end

			table.sort(tbl33)

			for _, sliced16 in ipairs(tbl33) do
				local str = string.format("%d - %s", sliced16, tbl31[sliced16])
				table.insert(tbl26, str)
				tbl27[str] = sliced16
			end

			table.sort(tbl32, function(arg, arg2)
				if arg.Rarity ~= arg2.Rarity then
					return arg.Rarity > arg2.Rarity
				end
				return arg.Name < arg2.Name
			end)

			for _, sliced16 in ipairs(tbl32) do
				local str = string.format("%s [%s]", sliced16.Name, sliced16.RarityName)

				if tbl29[str] then
					str = string.format("%s [%s] (%s)", sliced16.Name, sliced16.RarityName, sliced16.Category)
				end

				table.insert(tbl28, str)
				tbl29[str] = sliced16.Category
			end

			local tbl34 = {}
			local mutations = tbl.Mutations

			if type(mutations) == "table" and type(mutations.IdSet) == "table" then
				for k in pairs(mutations.IdSet) do
					table.insert(tbl34, tostring(k))
				end
			end

			table.sort(tbl34)

			for _, sliced16 in ipairs(tbl34) do
				table.insert(tbl30, sliced16)
			end

			local function slicedfn24(arg)
				for _, sliced16 in ipairs(tbl26) do
					if tbl27[sliced16] == arg then
						return sliced16
					end
				end

				return tbl26[1]
			end

			espSection:CreateDropdown({
				Name = "ESP Min Rarity",
				Note = "Show eggs of the chosen rarity and every rarity above it",
				Options = tbl26,
				Default = slicedfn24(5),
				SubOf = tbl25.Eggs,
				Callback = function(arg)
					tbl21.MinRarity = tbl27[type(arg) == "table" and arg[1] or arg] or 0
					slicedfn21()
				end,
			})
		end

		slicedfn6(espSection:CreateMultiDropdown({
			Name = "ESP Show Info",
			Options = tbl15,
			Default = tbl16,
			SubOf = tbl25.Eggs,
			Callback = function(arg)
				tbl21.Info = slicedfn23(arg)
				slicedfn21()
			end,
		}))

		do
			local tbl26 = {
				["K/s"] = { Min = 0, Max = 1000, Mult = 1000 },
				["M/s"] = { Min = 0, Max = 1000, Mult = 1000000 },
				["B/s"] = { Min = 0, Max = 100, Mult = 1e9 },
			}

			local slicedn13 = 0
			local str = "M/s"

			local function slicedfn24(arg, arg2)
				if arg ~= nil then
					slicedn13 = math.max(0, math.floor(tonumber(arg) or slicedn13))
				end

				if arg2 ~= nil then
					str = tostring(arg2)
				end

				tbl21.MinValue = slicedn13 * (tbl26[str] or tbl26["M/s"]).Mult
				slicedfn21()
			end

			slicedfn5(espSection, {
				Name = "Min ESP Value",
				SubOf = tbl25.Eggs,
				Legacy = "ESP Min Value",
				SectionName = "ESP",
				OnRaw = function(arg)
					slicedfn24(math.floor(arg / 1000), "K/s")
				end,
			})
		end

		espSection:CreateSlider({
			Name = "ESP Egg Size",
			Min = 50,
			Max = 200,
			Default = 75,
			Increment = 5,
			Unit = "%",
			SubOf = tbl25.Eggs,
			Callback = function(arg)
				local num = tonumber(arg)

				if num and tbl21.SizeScale ~= num / 100 then
					tbl21.SizeScale = num / 100
					slicedfn22()
				end
			end,
		})

		do
			local slicedn13 = 1
			local slicedn14 = 0.75

			local tbl26 = {
				Sleeping = tbl6.Palettes.Accent,
				Waking = tbl6.Palettes.Gold,
				Chasing = tbl6.Palettes.Red,
			}

			local orange = tbl6.Palettes.Orange
			local tbl27 = {}
			local tbl28 = {}
			local flag6 = false
			local sliced16 = nil

			local function slicedfn24(arg)
				local attribute = arg:GetAttribute("GuardState")
				if attribute == "Sleeping" then
					return "Sleeping"
				end

				if attribute == "Waking" then
					return "Waking Up"
				end

				if attribute == "Chasing" then
					local attribute2 = arg:GetAttribute("TargetPlayer")
					if attribute2 == tostring(localPlayer.UserId) then
						return "Chasing You"
					end
					local playerByUserId = tonumber(attribute2) and Players:GetPlayerByUserId(tonumber(attribute2))
					return playerByUserId and "Chasing " .. playerByUserId.DisplayName or "Chasing"
				end

				return attribute and tostring(attribute) or "Awake"
			end

			local function slicedfn25(arg, arg2)
				local sliced17 = tbl26[arg2:GetAttribute("GuardState")] or orange
				arg.Highlight.FillColor = sliced17.Outline
				arg.Highlight.OutlineColor = sliced17.Outline
				tbl6.SetRow(arg.StateRow, slicedfn24(arg2), sliced17)
			end

			local function slicedfn26(arg)
				local floor = math.floor
				arg.Tag.Size = UDim2.fromOffset(tbl6.ScaledWidth(115, slicedn14), floor(tbl6.RowHeight(slicedn14) * 1.6))
			end

			local function slicedfn27(arg)
				local sliced17 = tbl27[arg]
				if not sliced17 then
					return
				end
				tbl27[arg] = nil
				tbl6.DisconnectAll(sliced17.Connections)
				sliced17.Highlight:Destroy()
				sliced17.Tag:Destroy()
			end

			local function slicedfn28(arg, adornee)
				if tbl27[adornee] then
					return
				end
				local sliced17 = tbl6.FindGuardRoot(adornee)
				if not sliced17 then
					return
				end

				if not sliced16 or not sliced16.Parent then
					sliced16 = tbl6.CreateRuntime()
				end

				local highlight = Instance.new("Highlight")
				highlight.Name = slicedfn3()
				highlight.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
				highlight.FillTransparency = 0.76
				highlight.OutlineTransparency = 0.02
				highlight.Adornee = adornee
				highlight.Parent = sliced16
				local ok, result, result2 = pcall(adornee.GetBoundingBox, adornee)
				local flag7 = ok and typeof(result) == "CFrame"
				local slicedn15 = 6

				if flag7 then
					slicedn15 = result.Position.Y + result2.Y * 0.5 - sliced17.Position.Y + slicedn13
				end

				local sliced18, sliced19 = tbl6.CreateTag(sliced16, math.huge)
				sliced18.Adornee = sliced17
				sliced18.StudsOffsetWorldSpace = Vector3.new(0, slicedn15, 0)
				local sliced20 = tbl6.CreateTextRow(sliced19, tbl6.StatusFont, 1, 0.45)
				local sliced21 = tbl6.CreateTextRow(sliced19, tbl6.StatusFont, 2, 0.55)
				local sheen = tbl6.Palettes.Sheen
				tbl6.SetRow(sliced20, tostring(arg) .. " Guard", sheen)
				local tbl29 = { Highlight = highlight, Tag = sliced18, StateRow = sliced21, Connections = {} }
				tbl27[adornee] = tbl29
				slicedfn26(tbl29)
				slicedfn25(tbl29, adornee)

				local function slicedfn29()
					slicedfn25(tbl29, adornee)
				end

				table.insert(tbl29.Connections, adornee:GetAttributeChangedSignal("GuardState"):Connect(slicedfn29))
				table.insert(tbl29.Connections, adornee:GetAttributeChangedSignal("TargetPlayer"):Connect(slicedfn29))

				table.insert(tbl29.Connections, adornee.AncestryChanged:Connect(function()
					if not adornee:IsDescendantOf(workspace) then
						slicedfn27(adornee)
					end
				end))
			end

			local function slicedfn29()
				flag6 = false
				tbl6.DisconnectAll(tbl28)

				for k in pairs(tbl27) do
					slicedfn27(k)
				end

				if sliced16 then
					sliced16:Destroy()
					sliced16 = nil
				end
			end

			local function slicedfn30()
				if flag6 then
					return
				end
				flag6 = true
				tbl28 = tbl6.WatchGuards(slicedfn28)
			end

			local sliced17 = nil
			local flag7 = false
			local flag8 = false

			local function slicedfn31()
				if flag8 then
					return
				end

				if tbl6.ReadToggle(sliced17, flag7) then
					slicedfn30()
				elseif flag6 then
					slicedfn29()
				end
			end

			slicedfn4(function()
				flag8 = true
				slicedfn29()
			end)

			sliced17 = espSection:CreateToggle({
				Name = "ESP Guards",
				Default = false,
				Callback = function(arg)
					flag7 = arg == true
					tbl6.SyncSoon(slicedfn31)
				end,
			})

			espSection:CreateSlider({
				Name = "ESP Guard Size",
				Min = 50,
				Max = 200,
				Default = 75,
				Increment = 5,
				Unit = "%",
				SubOf = sliced17,
				Callback = function(arg)
					local num = tonumber(arg)

					if num and slicedn14 ~= num / 100 then
						slicedn14 = num / 100

						for _, sliced18 in pairs(tbl27) do
							slicedfn26(sliced18)
						end
					end
				end,
			})
		end

		do
			local tbl26 = {
				{ Id = "LostPart1", Label = "Mechanical Gear" },
				{ Id = "LostPart2", Label = "Wiring Harness" },
			}

			local sliced16 = tbl6.PaletteFromColor(Color3.fromRGB(255, 216, 61))
			local accent = tbl6.Palettes.Accent
			local sliced17 = nil
			local tbl27 = {}
			local flag6 = false
			local connection = nil
			local sliced18 = nil
			local flag7 = false
			local flag8 = false

			local function slicedfn24(arg)
				local sliced19 = tbl27[arg]
				if not sliced19 then
					return
				end
				tbl27[arg] = nil

				pcall(function()
					sliced19.Highlight:Destroy()
					sliced19.Tag:Destroy()
				end)
			end

			local function slicedfn25()
				local drScrambleEvent = workspace:FindFirstChild("DrScrambleEvent")

				for _, sliced19 in ipairs(tbl26) do
					local sliced20 = drScrambleEvent and drScrambleEvent:FindFirstChild(sliced19.Id)
					local hitbox = sliced20 and (sliced20:FindFirstChild("Hitbox", true) or sliced20.PrimaryPart or sliced20:FindFirstChildWhichIsA("BasePart", true))
					local tbl28 = tbl27[sliced19.Id]

					if tbl28 and (tbl28.Model ~= sliced20 or not hitbox) then
						slicedfn24(sliced19.Id)
						tbl28 = nil
					end

					if hitbox and not tbl28 then
						if not sliced17 or not sliced17.Parent then
							sliced17 = tbl6.CreateRuntime()
						end

						local highlight = Instance.new("Highlight")
						highlight.Name = slicedfn3()
						highlight.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
						highlight.FillTransparency = 0.7
						highlight.OutlineTransparency = 0.02
						highlight.Adornee = sliced20
						highlight.Parent = sliced17
						local sliced21, sliced22 = tbl6.CreateTag(sliced17, 25000)
						sliced21.Adornee = hitbox
						sliced21.StudsOffsetWorldSpace = Vector3.new(0, 4, 0)
						local floor = math.floor
						sliced21.Size = UDim2.fromOffset(tbl6.ScaledWidth(160), floor(tbl6.RowHeight() * 1.6))
						local sliced23 = tbl6.CreateTextRow(sliced22, tbl6.StatusFont, 1, 0.5)
						local sliced24 = tbl6.CreateTextRow(sliced22, tbl6.StatusFont, 2, 0.5)
						tbl6.SetRow(sliced23, sliced19.Label, tbl6.Palettes.Sheen)
						tbl28 = { Model = sliced20, Hitbox = hitbox, Highlight = highlight, Tag = sliced21, InfoRow = sliced24 }
						tbl27[sliced19.Id] = tbl28
					end

					if tbl28 then
						local flag9 = type(tbl4.ScrambleLostPart) == "function" and tbl4.ScrambleLostPart(sliced19.Id) == true
						local sliced21 = flag9 and accent or sliced16
						tbl6.SetRow(tbl28.InfoRow, flag9 and "Collected" or string.format("%d studs", math.floor(tbl4.DistanceTo(tbl28.Hitbox.Position))), sliced21)
						tbl28.Highlight.FillColor = sliced21.Outline
						tbl28.Highlight.OutlineColor = sliced21.Outline
					end
				end
			end

			local function slicedfn26()
				flag6 = false

				if connection then
					connection:Disconnect()
					connection = nil
				end

				for k in pairs(tbl27) do
					slicedfn24(k)
				end

				if sliced17 then
					sliced17:Destroy()
					sliced17 = nil
				end
			end

			local function slicedfn27()
				if flag6 then
					return
				end
				flag6 = true
				local slicedn13 = 1

				connection = RunService.Heartbeat:Connect(function(deltaTime)
					slicedn13 += deltaTime

					if slicedn13 >= 0.3 then
						slicedn13 = 0
						pcall(slicedfn25)
					end
				end)
			end

			local function slicedfn28()
				if flag8 then
					return
				end

				if tbl6.ReadToggle(sliced18, flag7) then
					slicedfn27()
				elseif flag6 then
					slicedfn26()
				end
			end

			slicedfn4(function()
				flag8 = true
				slicedfn26()
			end)

			sliced18 = espSection:CreateToggle({
				Name = "ESP Lost Parts",
				Default = false,
				Callback = function(arg)
					flag7 = arg == true
					tbl6.SyncSoon(slicedfn28)
				end,
			})
		end

		local TextService = game:GetService("TextService")
		local font = Font.new("rbxasset://fonts/families/GothamSSm.json", Enum.FontWeight.ExtraBold, Enum.FontStyle.Normal)
		local sliced16

		do
			local colorSequence = ColorSequence.new
			local tbl26 = {}
			local sliced17 = ColorSequenceKeypoint.new(0, Color3.fromRGB(138, 255, 205))
			local sliced18 = ColorSequenceKeypoint.new(0.5, Color3.fromRGB(125, 225, 255))
			tbl26[1] = sliced17
			tbl26[2] = sliced18

			do
				local values = table.pack(ColorSequenceKeypoint.new(1, Color3.fromRGB(210, 135, 255)))
				table.move(values, 1, values.n, 3, tbl26)
			end

			sliced16 = colorSequence(tbl26)
		end

		local colorSequence

		colorSequence = ColorSequence.new({
			ColorSequenceKeypoint.new(0, Color3.fromRGB(7, 73, 66)),
			ColorSequenceKeypoint.new(1, Color3.fromRGB(35, 17, 79)),
		})

		local flag6 = false
		local slicedn13 = 0
		local sliced17 = nil
		local tbl26 = {}
		local tbl27 = {}
		local tbl28 = {}
		local slicedn14, tbl29, sliced18, flag7, flag8

		do
			local tbl30 = {}
			slicedn14 = 0.75
			tbl29 = { Name = true, Username = false, Avatar = false, Tool = true }
			sliced18 = nil
			flag7 = false
			flag8 = false

			local function slicedfn24(arg)
				local str = tostring(arg or "")
				if str:match("^%d+$") then
					return "rbxassetid://" .. str
				end
				return str
			end

			local function slicedfn25(arg)
				if not arg or not arg:IsA("Tool") then
					return ""
				end
				local sliced19 = slicedfn24(arg.TextureId)
				if sliced19 ~= "" then
					return sliced19
				end

				for _, sliced20 in ipairs({ "Icon", "Image", "Thumbnail", "TextureId" }) do
					local attribute = arg:GetAttribute(sliced20)
					if type(attribute) == "string" and slicedfn24(attribute) ~= "" then
						return slicedfn24(attribute)
					end
				end

				for _, descendant in ipairs(arg:GetDescendants()) do
					if descendant:IsA("Decal") or descendant:IsA("Texture") then
						sliced19 = slicedfn24(descendant.Texture)
					elseif descendant:IsA("ImageLabel") or descendant:IsA("ImageButton") then
						sliced19 = slicedfn24(descendant.Image)
					end

					if sliced19 ~= "" then
						return sliced19
					end
				end

				return ""
			end

			local function slicedfn26()
				local currentCamera = workspace.CurrentCamera
				return math.max(1, math.floor(math.clamp((currentCamera and currentCamera.ViewportSize.Y or 1080) * 0.024, 26, 35) * slicedn14))
			end

			local function slicedfn27(text, size)
				local str = text .. "@" .. size
				local sliced19 = tbl30[str]
				if sliced19 then
					return sliced19
				end
				local getTextBoundsParams = Instance.new("GetTextBoundsParams")
				getTextBoundsParams.Text = text
				getTextBoundsParams.Font = font
				getTextBoundsParams.Size = size
				getTextBoundsParams.Width = 1000

				local ok, result = pcall(function()
					return TextService:GetTextBoundsAsync(getTextBoundsParams)
				end)

				getTextBoundsParams:Destroy()
				ok = ok and result.X

				if not ok then
					ok = (utf8.len(text) or #text) * size * 0.56
				end

				tbl30[str] = ok
				return ok
			end

			local function slicedfn28(arg, color3, arg2, arg3)
				arg.ApplyStrokeMode = Enum.ApplyStrokeMode.Contextual
				arg.Color = color3
				arg.LineJoinMode = Enum.LineJoinMode.Round
				arg.Transparency = 0

				arg.Thickness = pcall(function()
					arg.StrokeSizingMode = Enum.StrokeSizingMode.ScaledSize
				end) and arg2 or arg3
			end

			local function createTextLabel(parent, zIndex)
				local textLabel = Instance.new("TextLabel")
				textLabel.Name = slicedfn3()
				textLabel.AnchorPoint = Vector2.new(0, 0.5)
				textLabel.BackgroundTransparency = 1
				textLabel.FontFace = font
				textLabel.Text = ""
				textLabel.TextScaled = true
				textLabel.TextStrokeTransparency = 1
				textLabel.TextXAlignment = Enum.TextXAlignment.Center
				textLabel.TextYAlignment = Enum.TextYAlignment.Center
				textLabel.ZIndex = zIndex
				textLabel.Parent = parent
				return textLabel
			end

			local function createImageLabel(parent, zIndex)
				local imageLabel = Instance.new("ImageLabel")
				imageLabel.Name = slicedfn3()
				imageLabel.AnchorPoint = Vector2.new(0, 0.5)
				imageLabel.BackgroundTransparency = 1
				imageLabel.ScaleType = Enum.ScaleType.Fit
				imageLabel.ZIndex = zIndex
				imageLabel.Parent = parent
				local uiAspectRatioConstraint = Instance.new("UIAspectRatioConstraint")
				uiAspectRatioConstraint.Name = slicedfn3()
				uiAspectRatioConstraint.AspectRatio = 1
				uiAspectRatioConstraint.Parent = imageLabel
				return imageLabel
			end

			local function slicedfn29(arg)
				local sliced19 = slicedfn26()
				local visible = tbl29.Name == true or tbl29.Username == true
				local visible2 = tbl29.Avatar == true
				local visible3 = tbl29.Tool == true and arg.ToolIcon.Image ~= ""
				local slicedn15 = visible2 and math.floor(sliced19 * 0.72) or 0
				local slicedn16 = visible3 and math.floor(sliced19 * 0.82) or 0
				local slicedn17 = math.floor(sliced19 * 0.7)
				local slicedn18 = math.max(1, math.floor(sliced19 * 0.04))
				local name = tbl29.Username == true and arg.Player.Name or arg.Player.DisplayName
				arg.Name.Text = name
				arg.Shadow.Text = name
				local slicedn19 = visible and math.floor(math.clamp(slicedfn27(name, slicedn17) + 4, slicedn17, 230)) or 0
				local slicedn20 = 0
				local slicedn21 = 0

				if visible2 then
					slicedn20 = 0 + slicedn15
				end

				local slicedn22 = 0

				if visible then
					if not (slicedn20 > 0) then
						slicedn22 = slicedn20
					else
						slicedn22 = slicedn20 + slicedn18
					end

					slicedn20 = slicedn22 + slicedn19
				end

				local slicedn23 = 0

				if visible3 then
					if not (slicedn20 > 0) then
						slicedn23 = slicedn20
					else
						slicedn23 = slicedn20 + slicedn18
					end

					slicedn20 = slicedn23 + slicedn16
				end

				local slicedn24 = math.max(slicedn20, 1)
				local slicedn25 = 1 / slicedn24
				local slicedn26 = 1 / sliced19
				arg.Billboard.Size = UDim2.fromOffset(slicedn24, sliced19)
				arg.Avatar.Visible = visible2
				arg.Name.Visible = visible
				arg.Shadow.Visible = visible
				arg.ToolIcon.Visible = visible3
				arg.ToolShadow.Visible = visible3
				arg.Avatar.Position = UDim2.fromScale(slicedn21 / slicedn24, 0.5)
				arg.Avatar.Size = UDim2.fromScale(slicedn15 / slicedn24, slicedn15 / sliced19)
				arg.Name.Position = UDim2.fromScale(slicedn22 / slicedn24, 0.5)
				arg.Name.Size = UDim2.fromScale(slicedn19 / slicedn24, slicedn17 / sliced19)
				arg.Shadow.Position = UDim2.fromScale(slicedn22 / slicedn24 + slicedn25, 0.5 + slicedn26)
				arg.Shadow.Size = arg.Name.Size
				arg.ToolIcon.Position = UDim2.fromScale(slicedn23 / slicedn24, 0.5)
				arg.ToolIcon.Size = UDim2.fromScale(slicedn16 / slicedn24, slicedn16 / sliced19)
				arg.ToolShadow.Position = UDim2.fromScale(slicedn23 / slicedn24 + slicedn25, 0.5 + slicedn26)
				arg.ToolShadow.Size = arg.ToolIcon.Size
			end

			local function slicedfn30(arg, adornee, arg2, adornee2)
				local highlight = Instance.new("Highlight")
				highlight.Name = slicedfn3()
				highlight.Adornee = adornee
				highlight.DepthMode = Enum.HighlightDepthMode.AlwaysOnTop
				highlight.FillColor = Color3.fromRGB(0, 67, 148)
				highlight.FillTransparency = 0.76
				highlight.OutlineColor = Color3.fromRGB(72, 207, 255)
				highlight.OutlineTransparency = 0.02
				highlight.Parent = sliced17
				adornee2 = adornee2 or arg2
				local slicedn15 = 3.1

				if adornee2 ~= arg2 then
					slicedn15 = math.clamp(arg2.Position.Y - adornee2.Position.Y + 3.1, 3.8, 6)
				end

				local billboardGui = Instance.new("BillboardGui")
				billboardGui.Name = slicedfn3()
				billboardGui.Adornee = adornee2
				billboardGui.AlwaysOnTop = true
				billboardGui.LightInfluence = 0
				billboardGui.MaxDistance = math.huge
				billboardGui.Size = UDim2.fromOffset(1, 1)
				billboardGui.StudsOffsetWorldSpace = Vector3.new(0, slicedn15, 0)
				billboardGui.Parent = sliced17
				local frame = Instance.new("Frame")
				frame.Name = slicedfn3()
				frame.Size = UDim2.fromScale(1, 1)
				frame.BackgroundTransparency = 1
				frame.Parent = billboardGui
				local sliced19 = createImageLabel(frame, 2)
				sliced19.ScaleType = Enum.ScaleType.Crop
				local uiCorner = Instance.new("UICorner")
				uiCorner.Name = slicedfn3()
				uiCorner.CornerRadius = UDim.new(1, 0)
				uiCorner.Parent = sliced19
				local sliced20 = createTextLabel(frame, 1)
				sliced20.TextColor3 = Color3.fromRGB(7, 19, 34)
				sliced20.TextTransparency = 0.05
				local sliced21 = createTextLabel(frame, 2)
				sliced21.TextColor3 = Color3.fromRGB(255, 255, 255)
				local uiStroke = Instance.new("UIStroke")
				uiStroke.Name = slicedfn3()
				slicedfn28(uiStroke, Color3.fromRGB(255, 255, 255), 0.044, 1.4)
				uiStroke.Parent = sliced21
				local uiGradient = Instance.new("UIGradient")
				uiGradient.Name = slicedfn3()
				uiGradient.Color = colorSequence
				uiGradient.Rotation = 90
				uiGradient.Parent = uiStroke
				local uiGradient2 = Instance.new("UIGradient")
				uiGradient2.Name = slicedfn3()
				uiGradient2.Color = sliced16
				uiGradient2.Rotation = 90
				uiGradient2.Parent = sliced21
				local sliced22 = createImageLabel(frame, 1)
				sliced22.ImageColor3 = Color3.fromRGB(0, 0, 0)
				sliced22.ImageTransparency = 0.35

				local tbl31 = {
					Player = arg,
					Highlight = highlight,
					Billboard = billboardGui,
					Avatar = sliced19,
					Shadow = sliced20,
					Name = sliced21,
					ToolShadow = sliced22,
					ToolIcon = createImageLabel(frame, 2),
				}

				slicedfn29(tbl31)
				return tbl31
			end

			local function slicedfn31(arg)
				if arg.NameHumanoid and arg.NameHumanoid.Parent and arg.NameDistance ~= nil then
					pcall(function()
						arg.NameHumanoid.NameDisplayDistance = arg.NameDistance
					end)
				end

				arg.NameHumanoid = nil
				arg.NameDistance = nil
			end

			local function slicedfn32(arg, arg2)
				local humanoid = arg2 and arg2:FindFirstChildOfClass("Humanoid")
				if not humanoid then
					return
				end

				if arg.NameHumanoid ~= humanoid then
					slicedfn31(arg)
					arg.NameHumanoid = humanoid
					arg.NameDistance = humanoid.NameDisplayDistance
				end

				pcall(function()
					humanoid.NameDisplayDistance = 0
				end)
			end

			local function slicedfn33(arg)
				tbl6.DisconnectAll(arg.CharacterConnections)

				if arg.Tag then
					pcall(function()
						arg.Tag.Highlight:Destroy()
					end)

					pcall(function()
						arg.Tag.Billboard:Destroy()
					end)

					arg.Tag = nil
				end

				slicedfn31(arg)
				arg.Character = nil
			end

			local function slicedfn34(arg)
				if not arg.Tag or not arg.Character then
					return
				end
				local sliced19 = slicedfn25(arg.Character:FindFirstChildOfClass("Tool"))
				arg.Tag.ToolIcon.Image = sliced19
				arg.Tag.ToolShadow.Image = sliced19
				slicedfn29(arg.Tag)
			end

			local function slicedfn35(arg, arg2, arg3)
				local image = tbl28[arg2.UserId]

				if image == nil then
					local ok, result = pcall(function()
						return Players:GetUserThumbnailAsync(arg2.UserId, Enum.ThumbnailType.HeadShot, Enum.ThumbnailSize.Size100x100)
					end)

					image = ok and result or ""
					tbl28[arg2.UserId] = image
				end

				if flag6 and arg.Version == arg3 and arg.Tag then
					arg.Tag.Avatar.Image = image
				end
			end

			local function slicedfn36(arg, arg2, character)
				slicedfn33(arg)
				arg.Version = arg.Version + 1
				local version = arg.Version
				if not flag6 or not character then
					return
				end
				arg.Character = character

				task.spawn(function()
					local head = character:FindFirstChild("Head") or character:WaitForChild("Head", 5)
					if not flag6 or arg.Version ~= version or not head or not head:IsA("BasePart") or not character:IsDescendantOf(workspace) then
						return
					end

					if not sliced17 or not sliced17.Parent then
						sliced17 = tbl6.CreateRuntime()
					end

					local humanoidRootPart = character:FindFirstChild("HumanoidRootPart")
					arg.Tag = slicedfn30(arg2, character, head, humanoidRootPart and humanoidRootPart:IsA("BasePart") and humanoidRootPart or nil)
					slicedfn32(arg, character)

					local function slicedfn37()
						task.defer(function()
							if flag6 and arg.Version == version then
								slicedfn34(arg)
							end
						end)
					end

					table.insert(arg.CharacterConnections, character.ChildAdded:Connect(function(child)
						if child:IsA("Tool") then
							slicedfn37()
						elseif child:IsA("Humanoid") then
							slicedfn32(arg, character)
						end
					end))

					table.insert(arg.CharacterConnections, character.ChildRemoved:Connect(function(child)
						if child:IsA("Tool") then
							slicedfn37()
						end
					end))

					table.insert(arg.CharacterConnections, character.AncestryChanged:Connect(function()
						if arg.Version == version and not character:IsDescendantOf(workspace) then
							arg.Version = arg.Version + 1
							slicedfn33(arg)
						end
					end))

					slicedfn34(arg)
					slicedfn35(arg, arg2, version)
				end)
			end

			local function slicedfn37(player)
				local sliced19 = tbl26[player]
				if not sliced19 then
					return
				end
				sliced19.Version = sliced19.Version + 1
				slicedfn33(sliced19)
				tbl6.DisconnectAll(sliced19.PlayerConnections)
				tbl26[player] = nil
			end

			local function slicedfn38(player)
				if player == localPlayer or tbl26[player] then
					return
				end

				local tbl31 = {
					Version = 0,
					Character = nil,
					Tag = nil,
					NameHumanoid = nil,
					NameDistance = nil,
					CharacterConnections = {},
					PlayerConnections = {},
				}

				tbl26[player] = tbl31

				table.insert(tbl31.PlayerConnections, player.CharacterAdded:Connect(function(character)
					slicedfn36(tbl31, player, character)
				end))

				table.insert(tbl31.PlayerConnections, player.CharacterRemoving:Connect(function(character)
					if tbl31.Character == character then
						tbl31.Version = tbl31.Version + 1
						slicedfn33(tbl31)
					end
				end))

				slicedfn36(tbl31, player, player.Character)
			end

			local function slicedfn39()
				for _, sliced19 in pairs(tbl26) do
					if sliced19.Tag then
						slicedfn29(sliced19.Tag)
					end
				end
			end

			local function slicedfn40()
				flag6 = false
				slicedn13 += 1
				tbl6.DisconnectAll(tbl27)
				local tbl31 = {}

				for k in pairs(tbl26) do
					table.insert(tbl31, k)
				end

				for _, sliced19 in ipairs(tbl31) do
					slicedfn37(sliced19)
				end

				if sliced17 then
					sliced17:Destroy()
					sliced17 = nil
				end
			end

			local function slicedfn41()
				if flag6 then
					return
				end
				flag6 = true
				slicedn13 += 1
				local sliced19 = slicedn13
				sliced17 = tbl6.CreateRuntime()

				for _, player in ipairs(Players:GetPlayers()) do
					slicedfn38(player)
				end

				table.insert(tbl27, Players.PlayerAdded:Connect(slicedfn38))
				table.insert(tbl27, Players.PlayerRemoving:Connect(slicedfn37))
				local currentCamera = workspace.CurrentCamera

				if currentCamera then
					table.insert(tbl27, currentCamera:GetPropertyChangedSignal("ViewportSize"):Connect(slicedfn39))
				end

				task.spawn(function()
					while true do
						if flag6 and sliced19 == slicedn13 then
							task.wait(1)

							if not (not flag6 or sliced19 ~= slicedn13) then
								for k, sliced20 in pairs(tbl26) do
									local character = k.Character
									local adornee = sliced20.Tag and sliced20.Tag.Billboard.Parent and sliced20.Tag.Billboard.Adornee and sliced20.Tag.Billboard.Adornee:IsDescendantOf(workspace)

									if character and character:IsDescendantOf(workspace) and (sliced20.Character ~= character or not adornee) then
										slicedfn36(sliced20, k, character)
									end
								end

								continue
							end
						end

						break
					end
				end)
			end

			local function slicedfn42()
				if flag8 then
					return
				end

				if tbl6.ReadToggle(sliced18, flag7) then
					slicedfn41()
				elseif flag6 then
					slicedfn40()
				end
			end

			slicedfn4(function()
				flag8 = true
				slicedfn40()
			end)

			sliced18 = espSection:CreateToggle({
				Name = "ESP Players",
				Default = false,
				Callback = function(arg)
					flag7 = arg == true
					tbl6.SyncSoon(slicedfn42)
				end,
			})

			slicedfn6(espSection:CreateMultiDropdown({
				Name = "ESP Player Info",
				Options = { "Name", "Username", "Avatar", "Tool" },
				Default = { "Name", "Tool" },
				SubOf = sliced18,
				Callback = function(arg)
					local tbl31 = { Name = false, Username = false, Avatar = false, Tool = false }

					if type(arg) == "table" then
						for k, sliced19 in pairs(arg) do
							if type(sliced19) == "string" and tbl31[sliced19] ~= nil then
								tbl31[sliced19] = true
							elseif type(k) == "string" and sliced19 == true and tbl31[k] ~= nil then
								tbl31[k] = true
							end
						end
					end

					tbl29 = tbl31
					slicedfn39()
				end,
			}))

			espSection:CreateSlider({
				Name = "ESP Player Size",
				Min = 50,
				Max = 200,
				Default = 75,
				Increment = 5,
				Unit = "%",
				SubOf = sliced18,
				Callback = function(arg)
					local num = tonumber(arg)

					if num and slicedn14 ~= num / 100 then
						slicedn14 = math.clamp(num / 100, 0.5, 2)
						slicedfn39()
					end
				end,
			})
		end
	end

	local slicedn4 = 3
	local slicedn5 = 0.002
	local slicedn6 = 4
	local slicedn7 = 0.3
	local slicedn8 = 0.62
	local slicedn9 = 0.86
	local slicedn10 = 4.4262295081967213
	local slicedn11 = 1.392
	local slicedn12 = 1.03
	local tweenInfo = TweenInfo.new(0.3, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
	local tweenInfo2 = TweenInfo.new(0.24, Enum.EasingStyle.Quad, Enum.EasingDirection.In)
	local tweenInfo3 = TweenInfo.new(0.22, Enum.EasingStyle.Quad, Enum.EasingDirection.In)
	local tweenInfo4 = TweenInfo.new(0.3, Enum.EasingStyle.Back, Enum.EasingDirection.Out)
	local tweenInfo5 = TweenInfo.new(0.16, Enum.EasingStyle.Quad, Enum.EasingDirection.Out)
	local TweenService = game:GetService("TweenService")
	local color3 = Color3.fromRGB
	local slicedfn18

	slicedfn18 = function(arg)
		local tbl14 = {}

		for i, sliced10 in ipairs(arg) do
			tbl14[i] = ColorSequenceKeypoint.new(sliced10[1], sliced10[2])
		end

		return ColorSequence.new(tbl14)
	end

	local tbl14 = {}

	do
		local hud = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(0, 118, 255) }
		local tbl17 = { 1, color3(72, 204, 255) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		hud.Color = slicedfn18(tbl15)
		hud.Rotation = -90
		hud.Stroke = color3(0, 28, 76)
		hud.Light = color3(172, 226, 255)
		tbl14.Hud = hud
	end

	do
		local steal = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(60, 255, 0) }
		local tbl17 = { 1, color3(136, 255, 0) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		steal.Color = slicedfn18(tbl15)
		steal.Rotation = -90
		steal.Stroke = color3(11, 72, 0)
		steal.Light = color3(190, 255, 180)
		tbl14.Steal = steal
	end

	do
		local queued = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(118, 118, 132) }
		local tbl17 = { 1, color3(172, 172, 186) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		queued.Color = slicedfn18(tbl15)
		queued.Rotation = -90
		queued.Stroke = color3(28, 28, 34)
		queued.Light = color3(214, 214, 226)
		tbl14.Queued = queued
	end

	do
		local priorityOn = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(255, 247, 0) }
		local tbl17 = { 1, color3(255, 136, 0) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		priorityOn.Color = slicedfn18(tbl15)
		priorityOn.Rotation = 90
		priorityOn.Stroke = color3(0, 0, 0)
		priorityOn.Light = color3(132, 112, 0)
		tbl14.PriorityOn = priorityOn
	end

	do
		local cancel = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(214, 17, 17) }
		local tbl17 = { 1, color3(253, 20, 20) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		cancel.Color = slicedfn18(tbl15)
		cancel.Rotation = -90
		cancel.Stroke = color3(72, 0, 0)
		cancel.Light = color3(255, 103, 103)
		tbl14.Cancel = cancel
	end

	do
		local Sources = {}
		local tbl15 = {}
		local tbl16 = { 0, color3(132, 74, 255) }
		local tbl17 = { 0.34, color3(178, 74, 255) }
		local tbl18 = { 0.6, color3(255, 104, 206) }
		local tbl19 = { 0.78, color3(255, 168, 232) }
		local tbl20 = { 1, color3(146, 66, 255) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		tbl15[3] = tbl18
		tbl15[4] = tbl19
		tbl15[5] = tbl20
		Sources.Color = slicedfn18(tbl15)
		Sources.Rotation = -115
		Sources.Stroke = color3(44, 10, 80)
		Sources.Light = color3(226, 178, 255)
		tbl14.Sources = Sources
	end

	do
		local c3 = Color3.fromRGB
		local function moonStyle(style, a, b, strokeColor, fill)
			style.Color = ColorSequence.new(a, b)
			style.Rotation = 0
			style.Stroke = strokeColor
			style.StrokeSeq = ColorSequence.new({
				ColorSequenceKeypoint.new(0, strokeColor),
				ColorSequenceKeypoint.new(0.5, strokeColor:Lerp(c3(4, 7, 16), 0.65)),
				ColorSequenceKeypoint.new(1, strokeColor),
			})
			style.Fill = fill or c3(0, 0, 0)
			style.Light = strokeColor
		end
		-- hub look: black translucent fill, living stroke, gradient text
		local UC = SourcesLib.UI.C
		moonStyle(tbl14.Hud, UC.MOON2, UC.SILVER, UC.DEEP3, c3(30, 18, 20))
		moonStyle(tbl14.Steal, c3(255, 255, 255), UC.MOON2, UC.MOON2, UC.MOON)
		moonStyle(tbl14.Queued, UC.SILVER2, UC.SILVER, UC.DEEP3, c3(26, 22, 24))
		moonStyle(tbl14.PriorityOn, c3(255, 225, 140), c3(255, 190, 70), c3(255, 200, 60), c3(60, 44, 8))
		moonStyle(tbl14.Cancel, c3(255, 170, 170), c3(255, 110, 120), UC.RED, c3(86, 20, 28))

		SourcesLib.ThemeHooks[#SourcesLib.ThemeHooks + 1] = function(mapColor, mapSeq)
			for _, st in pairs(tbl14) do
				if type(st) == "table" then
					for k, v in pairs(st) do
						local t = typeof(v)

						if t == "Color3" then
							st[k] = mapColor(v)
						elseif t == "ColorSequence" then
							st[k] = mapSeq(v)
						end
					end
				end
			end
		end
		SourcesLib.RunThemeHooksFrom("Moon")
	end

	local slicedfn19

	do
		local tbl15 = {}
		local tbl16 = { 0, color3(255, 255, 255) }
		local tbl17 = { 0.2, color3(206, 212, 224) }
		local tbl18 = { 0.42, color3(74, 80, 94) }
		local tbl19 = { 0.58, color3(42, 46, 56) }
		local tbl20 = { 0.78, color3(158, 166, 182) }
		local tbl21 = { 1, color3(250, 252, 255) }
		tbl15[1] = tbl16
		tbl15[2] = tbl17
		tbl15[3] = tbl18
		tbl15[4] = tbl19
		tbl15[5] = tbl20
		tbl15[6] = tbl21
		local sliced10 = slicedfn18(tbl15)
		local tbl22 = {}
		local rarityGradients = nil

		slicedfn19 = function(arg)
			local sliced11 = tbl22[arg]
			if sliced11 then
				return sliced11
			end
			local directory = tbl.Assets and tbl.Assets.Directory
			local flag4 = type(directory) == "table" and directory[arg] or nil
			local rarity = type(flag4) == "table" and type(flag4.Rarity) == "table" and flag4.Rarity or nil
			local rarityGradient = rarity and rarity.RarityGradient or nil

			if rarity and typeof(rarityGradient) ~= "Instance" then
				if rarityGradients == nil then
					local assets = ReplicatedStorage:FindFirstChild("Assets")
					assets = assets and assets:FindFirstChild("UI")
					rarityGradients = assets and assets:FindFirstChild("RarityGradients") or false
				end

				rarityGradient = rarityGradients

				if rarityGradients then
					rarityGradient = rarityGradients:FindFirstChild(tostring(rarity._id or rarity.DisplayName or ""))
				end

				rarityGradient = rarityGradient and rarityGradient:FindFirstChild("RarityGradient") or nil
			end

			local str

			if rarity then
				str = tostring(rarity.DisplayName or rarity._id or "")
			else
				str = rarity
			end

			str = str or ""
			local color4 = rarity and typeof(rarity.Color) == "Color3" and rarity.Color or color3(255, 255, 255)
			local color5 = slicedfn18({ { 0, color4 }, { 1, color4 } })
			local gradientRotation

			if string.upper(str) == "SECRET" then
				gradientRotation = 90
				color5 = sliced10
			else
				local isUIGradient = typeof(rarityGradient) == "Instance" and rarityGradient:IsA("UIGradient")
				gradientRotation = 90

				if isUIGradient then
					color5 = rarityGradient.Color
					gradientRotation = rarityGradient.Rotation
				end
			end

			local icon = type(flag4) == "table" and flag4.Icon or nil

			if tonumber(icon) then
				icon = "rbxassetid://" .. tostring(icon)
			end

			local tbl23 = {}
			local flag5 = type(flag4) == "table"
			local name

			if flag5 then
				name = tostring(flag4.DisplayName or arg)
			else
				name = flag5
			end

			tbl23.Name = name or tostring(arg)
			tbl23.Icon = icon and tostring(icon) or ""
			local rarityNumber

			if rarity then
				rarityNumber = tonumber(rarity.RarityNumber or rarity.Rank)
			else
				rarityNumber = rarity
			end

			tbl23.RarityNumber = rarityNumber or 0
			tbl23.GradientColor = color5
			tbl23.GradientRotation = gradientRotation
			tbl23.EarningRate = type(flag4) == "table" and tonumber(flag4.EarningRate) or 0
			tbl22[arg] = tbl23
			return tbl23
		end
	end

	local slicedfn20

	slicedfn20 = function(arg, arg2)
		local slicedn13 = tonumber(arg.AssetScale) or 1
		local slicedn14 = slicedn13 > 5 and (slicedn13 / 5) ^ 1.2 * 19.637875755794113 or slicedn13 ^ 1.85
		local mutations = type(arg.Mutations) == "table" and arg.Mutations or {}

		if #mutations == 0 and type(arg.BaseMutation) == "string" and arg.BaseMutation ~= "" then
			mutations = { arg.BaseMutation }
		end

		local mutations2 = tbl.Mutations
		local flag4 = type(mutations2) == "table" and type(mutations2.EarningsFor) == "function"
		local slicedn15 = 1

		if flag4 then
			local ok, result = pcall(mutations2.EarningsFor, mutations)
			ok = ok and type(result) == "number"
			local slicedn16 = 1

			if ok then
				slicedn15 = result
			else
				slicedn15 = slicedn16
			end
		end

		return arg2.EarningRate * slicedn14 * slicedn15
	end

	local slicedfn21
	local tbl15 = { "", "K", "M", "B", "T", "Qa", "Qi", "Sx" }

	slicedfn21 = function(arg)
		local slicedn13 = tonumber(arg) or 0
		local slicedn14 = 1

		while slicedn13 >= 1000 and slicedn14 < #tbl15 do
			slicedn13 /= 1000
			slicedn14 += 1
		end

		local str = slicedn14 == 1 and tostring(math.floor(slicedn13)) or string.format("%.1f", math.floor(slicedn13 * 10) / 10)
		local str2 = tbl15[slicedn14] .. "/s"
		return "$" .. string.gsub(str, "%.0$", "") .. str2
	end

	local slicedfn22

	slicedfn22 = function(arg, text)
		if arg and arg.Text ~= text then
			arg.Text = text
		end
	end

	local flag4 = false
	local slicedn13 = 0
	local flag5 = false
	local sliced10 = nil
	local sliced11 = nil
	local sliced12 = nil
	local imageLabel = nil
	local sliced13 = nil
	local sliced14 = nil
	local position = nil
	local title = nil
	local sliced15 = nil
	local sliced16 = nil
	local sliced17 = nil
	local flag6 = false
	local sliced18 = sliced2:CreateState({ Name = "Steal Panel Open", Default = true })
	local flag7 = false
	local tween = nil
	local tween2 = nil
	local slicedn14 = 0
	local tbl16 = nil
	local tbl17 = nil
	local slicedn15 = 1
	local tbl18 = {}
	local tbl19 = {}
	local tbl20 = {}
	local uiStroke, thickness, flag8, flag9, flag10, slicedfn23, slicedfn24, slicedfn25, slicedfn26, tbl21
	local slicedfn27, slicedfn28

	do
		local obj = setmetatable({}, { __mode = "k" })
		uiStroke = nil
		thickness = nil
		flag8 = false
		flag9 = false
		flag10 = false
		slicedfn23 = nil

		slicedfn24 = function()
			local playerGui = localPlayer:FindFirstChildOfClass("PlayerGui")
			local hud = playerGui and playerGui:FindFirstChild("HUD")
			local gameHUD = hud and hud:FindFirstChild("GameHUD")
			local rightButtons = gameHUD and gameHUD:FindFirstChild("RightButtons")
			local activePets = playerGui and playerGui:FindFirstChild("ActivePets")

			local tbl22 = {
				Hud = hud,
				GameHud = gameHUD,
				Column = rightButtons,
				Eggs = rightButtons and rightButtons:FindFirstChild("EggsButton"),
				Pets = rightButtons and rightButtons:FindFirstChild("PetsButton"),
				ActivePets = activePets,
				GrowingEggs = playerGui and playerGui:FindFirstChild("GrowingEggs"),
			}

			if not (hud and gameHUD and rightButtons and tbl22.Eggs and tbl22.Pets and activePets and activePets:FindFirstChild("Frame")) then
				return nil
			end
			return tbl22
		end

		slicedfn25 = function(arg)
			local ok, result = pcall(function()
				return arg:Clone()
			end)

			if not ok or typeof(result) ~= "Instance" then
				return nil
			end

			for _, descendant in ipairs(result:GetDescendants()) do
				if descendant:IsA("LuaSourceContainer") then
					descendant:Destroy()
				end
			end

			return result
		end

		slicedfn26 = function(arg)
			arg.Name = slicedfn3()

			for _, descendant in ipairs(arg:GetDescendants()) do
				descendant.Name = slicedfn3()
			end
		end

		local slicedn16 = 2.3120369911193848
		local slicedn17 = 556
		local slicedn18 = 86.24
		tbl21 = { Panel = slicedn16, Hud = slicedn16 }

		local function slicedfn29(arg)
			if arg then
				local x = sliced14 and sliced14.AbsoluteSize.X or 0
				return x > 0 and slicedn16 * x / slicedn17 or nil
			end
			local button = sliced12 and sliced12.Button
			button = button and button.Size.X.Offset or 0
			return button > 0 and slicedn16 * button / slicedn18 or nil
		end

		local function slicedfn30(arg, arg2)
			local sliced19 = slicedfn29(arg2.Panel)

			if sliced19 and arg.Parent then
				arg.Thickness = arg2.Ratio * sliced19
			end
		end

		slicedfn27 = function(arg, arg2)
			local panel = arg2 and tbl21.Panel or tbl21.Hud

			if not panel or panel <= 0 then
				panel = 2.3120369911193848
			end

			for _, descendant in ipairs(arg:GetDescendants()) do
				if descendant:IsA("UIStroke") then
					local ok, result = pcall(function()
						return descendant.StrokeSizingMode
					end)

					if not ok or result ~= Enum.StrokeSizingMode.ScaledSize then
						local tbl22 = { Ratio = descendant.Thickness / panel, Panel = arg2 == true }
						obj[descendant] = tbl22
						slicedfn30(descendant, tbl22)
					end
				end
			end
		end

		slicedfn28 = function()
			for k, sliced19 in pairs(obj) do
				slicedfn30(k, sliced19)
			end
		end
	end

	local slicedfn29

	slicedfn29 = function()
		slicedfn28()
	end

	local slicedfn30

	slicedfn30 = function(arg)
		if not arg then
			return nil
		end

		return {
			Button = arg,
			Gradient = arg:FindFirstChildOfClass("UIGradient"),
			Stroke = arg:FindFirstChild("UIStroke"),
			Light = arg:FindFirstChild("UIStrokeClr"),
			Label = arg:FindFirstChild("Label") or arg:FindFirstChild("TextLabel"),
			Scale = arg:FindFirstChild("BtnScale"),
		}
	end

	local slicedfn31

	slicedfn31 = function(arg, style)
		if not arg or arg.Style == style then
			return
		end
		local hadStyle = arg.Style ~= nil
		arg.Style = style
		if hadStyle and arg.Pulse then
			task.spawn(arg.Pulse)
		end

		if arg.Gradient then
			arg.Gradient.Color = style.Color
			arg.Gradient.Rotation = style.Rotation
		end

		if arg.Stroke then
			if arg.Stroke:IsA("UIGradient") then
				arg.Stroke.Color = style.StrokeSeq or ColorSequence.new(style.Stroke)
			else
				arg.Stroke.Color = style.Stroke
			end
		end

		if style.Fill and arg.Button then
			arg.Button.BackgroundColor3 = style.Fill
		end

		if arg.Light then
			arg.Light.Color = style.Light
		end
	end

	local slicedfn32

	slicedfn32 = function(arg)
		if not arg then
			return
		end
		local scale = arg.Scale

		if not scale then
			scale = Instance.new("UIScale")
			scale.Parent = arg.Button
			arg.Scale = scale
		end

		local function slicedfn33(arg2)
			TweenService:Create(scale, tweenInfo5, { Scale = arg2 }):Play()
		end

		arg.Button.MouseEnter:Connect(function()
			slicedfn33(1.08)
		end)

		arg.Button.MouseLeave:Connect(function()
			slicedfn33(1)
		end)

		arg.Button.MouseButton1Down:Connect(function()
			slicedfn33(0.94)
		end)

		arg.Button.MouseButton1Up:Connect(function()
			slicedfn33(1.08)
		end)
	end

	local slicedfn33

	do
		local tweenInfo6 = TweenInfo.new(2.4, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true)
		local tweenInfo7 = TweenInfo.new(6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true)
		local tweenInfo8 = TweenInfo.new(1.6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true)
		local tbl22 = {}

		slicedfn33 = function(arg)
			for _, sliced19 in ipairs(tbl22) do
				pcall(function()
					sliced19:Cancel()
				end)
			end

			table.clear(tbl22)
			if not arg or SourcesLib.NoAnim then
				return
			end

			local function slicedfn34(arg2)
				tbl22[#tbl22 + 1] = arg2
				arg2:Play()
			end

			local gradient = arg.Gradient

			if gradient then
				gradient.Rotation = -115
				gradient.Offset = Vector2.new(-0.30000001192092896, 0)
				slicedfn34(TweenService:Create(gradient, tweenInfo6, { Offset = Vector2.new(0.30000001192092896, 0) }))
				slicedfn34(TweenService:Create(gradient, tweenInfo7, { Rotation = -65 }))
			end

			local light = arg.Light

			if light then
				light.Color = color3(226, 178, 255)
				slicedfn34(TweenService:Create(light, tweenInfo8, { Color = color3(255, 245, 255) }))
			end
		end
	end

	do
		local sliced19 = setthreadidentity or set_thread_identity

		local function slicedfn34()
			local eggState = tbl.EggState

			if type(eggState) == "table" and type(eggState.ReadFieldEggs) == "function" then
				local records = nil

				task.spawn(function()
					local ok, result = pcall(eggState.ReadFieldEggs)

					if ok and type(result) == "table" and type(result.Records) == "table" and next(result.Records) ~= nil then
						records = result.Records
					end
				end)

				if type(sliced19) == "function" then
					pcall(sliced19, 8)
				end

				if records then
					return records
				end
			end

			local rfEggWorldAskFieldEggSnapshot = networking:FindFirstChild("RF/EggWorld/AskFieldEggSnapshot")
			if not rfEggWorldAskFieldEggSnapshot or not rfEggWorldAskFieldEggSnapshot:IsA("RemoteFunction") then
				return nil
			end
			local flag11 = false
			local records = nil

			task.spawn(function()
				local ok, result = pcall(rfEggWorldAskFieldEggSnapshot.InvokeServer, rfEggWorldAskFieldEggSnapshot)

				if ok and type(result) == "table" and type(result.Records) == "table" then
					records = result.Records
				end

				flag11 = true
			end)

			local now = os.clock()

			while not flag11 and os.clock() - now < slicedn6 do
				RunService.Heartbeat:Wait()
			end

			return records
		end

		local function slicedfn35()
			local flag11 = sliced10 ~= nil

			if flag11 then
				flag11 = sliced10.ActivePets and sliced10.ActivePets.Enabled or sliced10.GrowingEggs and sliced10.GrowingEggs.Enabled
			end

			return flag11 or false
		end

		local function slicedfn36()
			local flag11 = false

			for _, sliced20 in ipairs({ sliced10.ActivePets, sliced10.GrowingEggs }) do
				if sliced20 and sliced20.Enabled then
					local frame = sliced20:FindFirstChild("Frame")
					frame = frame and frame:FindFirstChild("Close")
					local flag12 = frame and typeof(getconnections) == "function"
					local flag13 = false

					if flag12 then
						local ok, result = pcall(getconnections, frame.Activated)
						local flag14 = ok and type(result) == "table"
						local flag15 = false

						if flag14 then
							local sliced21, sliced22, sliced23 = ipairs(result)
							local flag16 = false

							for _, sliced24 in sliced21, sliced22, sliced23 do
								if pcall(function()
									sliced24:Fire()
								end) then
									flag16 = true
								end
							end

							flag13 = flag16
						else
							flag13 = flag15
						end
					end

					if not flag13 then
						sliced20.Enabled = false
					end

					flag11 = true
				end
			end

			return flag11
		end

		local function slicedfn37(arg, arg2)
			local column = sliced10 and sliced10.Column
			if not column or not column.Parent then
				return
			end

			if tween2 then
				tween2:Cancel()
				tween2 = nil
			end

			local position2 = column.Position
			local udim2 = UDim2.new(position2.X.Scale, arg and math.ceil(column.AbsoluteSize.X * slicedn12) or 0, position2.Y.Scale, position2.Y.Offset)
			if arg2 then
				column.Position = udim2
				return
			end
			tween2 = TweenService:Create(column, arg and tweenInfo3 or tweenInfo4, { Position = udim2 })
			tween2:Play()
		end

		local slicedn16 = 0.106
		local udim2 = UDim2.new(0.955, 0, 0.6, 0)
		local udim22 = UDim2.new(0.955 - slicedn16, 0, 0.6, 0)
		local udim23 = UDim2.new(0.2, 0, 0.56, 0)
		local slicedn17 = 0.955 - slicedn16

		local function slicedfn38(arg, visible)
			if arg and arg.Button.Visible ~= visible then
				arg.Button.Visible = visible
			end
		end

		local function slicedfn39(arg, rank, badgeStyle, arg2)
			local visible = rank ~= nil
			arg.Rank = rank
			slicedfn38(arg.Steal, not visible)
			slicedfn38(arg.Up, visible)
			slicedfn38(arg.Down, visible)
			slicedfn38(arg.Cancel, visible)

			if visible then
				slicedfn31(arg.Up, rank > 1 and tbl14.Hud or tbl14.Queued)
				slicedfn31(arg.Down, rank < (arg2 or rank) and tbl14.Hud or tbl14.Queued)
			end

			slicedfn31(arg.Star, rank == 1 and tbl14.PriorityOn or tbl14.Queued)

			if arg.Badge then
				if arg.Badge.Visible ~= visible then
					arg.Badge.Visible = visible
				end

				if visible then
					slicedfn22(arg.Badge, "#" .. rank)
					badgeStyle = badgeStyle and tbl14.Steal or tbl14.PriorityOn

					if arg.BadgeStyle ~= badgeStyle and arg.BadgeGradient then
						arg.BadgeStyle = badgeStyle
						arg.BadgeGradient.Color = badgeStyle.Color
						arg.BadgeGradient.Rotation = 90
					end
				end
			end
		end

		local flagReady = false
		local win = nil

		local function slicedfn40()
			if not tbl16 then
				return
			end
			local sliced20 = tbl4.Toggle(sliced5, false)

			if tbl16.On ~= sliced20 then
				tbl16.On = sliced20
				tbl16.ToggleHandle:Set(sliced20, false)
			end

			local method = tbl4.Method.Current()

			if tbl16.Mode ~= method then
				tbl16.Mode = method
				tbl16.GuardHandle:Set(method)
				local methodHandle = tbl4.SafeCarry.MethodHandle

				if tbl4.MethodReady and methodHandle and type(methodHandle.Set) == "function" then
					pcall(methodHandle.Set, methodHandle, method, false)
				end
			end

			if tbl16.SortShown ~= sliced4 then
				tbl16.SortShown = sliced4
				tbl16.SortHandle.SetText(tostring(sliced4))
			end
		end

		local slicedn18 = 4
		local tbl22 = {}
		local tbl23 = {}

		local function slicedfn41()
			if not sliced16 then
				return
			end
			slicedfn40()
			local tbl24 = {}

			for _, sliced20 in pairs(tbl19) do
				table.insert(tbl24, sliced20)
			end

			local tbl25 = {}
			local sliced20 = nil

			if type(tbl4.StealPlan) == "function" then
				task.spawn(function()
					local ok, result, result2 = pcall(tbl4.StealPlan)

					if ok and type(result) == "table" then
						tbl25 = result
						sliced20 = result2
					end
				end)
			end

			local tbl26 = {}

			for i, sliced21 in ipairs(tbl25) do
				if tbl26[sliced21] == nil then
					tbl26[sliced21] = i
				end
			end

			local sliced21 = sliced4

			table.sort(tbl24, function(arg, arg2)
				local sliced22 = tbl26[arg.Uid]
				local sliced23 = tbl26[arg2.Uid]
				if sliced22 ~= nil ~= (sliced23 ~= nil) then
					return sliced22 ~= nil
				end

				if sliced22 and sliced23 then
					return sliced22 < sliced23
				end

				if sliced21 == tbl5[1] and arg.Style.RarityNumber ~= arg2.Style.RarityNumber then
					return arg.Style.RarityNumber > arg2.Style.RarityNumber
				end
				local flag11 = sliced21 == tbl5[2]

				if flag11 then
					flag11 = (arg.Weight or 0) ~= (arg2.Weight or 0)
				end

				if flag11 then
					return (arg.Weight or 0) > (arg2.Weight or 0)
				end

				if sliced21 == tbl5[5] and arg.Value ~= arg2.Value then
					return arg.Value < arg2.Value
				end

				if arg.Value ~= arg2.Value then
					return arg.Value > arg2.Value
				end
				return arg.Uid < arg2.Uid
			end)

			local now = os.clock()
			local tbl27 = {}
			local tbl28 = {}

			for _, sliced22 in ipairs(tbl24) do
				local sliced23 = tbl22[sliced22.Uid]

				if sliced23 and sliced23 > now and tbl23[sliced22.Uid] then
					table.insert(tbl28, sliced22)
				else
					tbl22[sliced22.Uid] = nil
					table.insert(tbl27, sliced22)
				end
			end

			table.sort(tbl28, function(arg, arg2)
				return tbl23[arg.Uid] < tbl23[arg2.Uid]
			end)

			for _, sliced22 in ipairs(tbl28) do
				table.insert(tbl27, math.clamp(tbl23[sliced22.Uid], 1, #tbl27 + 1), sliced22)
			end

			table.clear(tbl23)

			for i, sliced22 in ipairs(tbl27) do
				tbl23[sliced22.Uid] = i
				local sliced23 = tbl18[sliced22.Uid]

				if sliced23 then
					if sliced23.Frame.LayoutOrder ~= i then
						sliced23.Frame.LayoutOrder = i
					end

					slicedfn39(sliced23, tbl26[sliced22.Uid], sliced22.Uid == sliced20, #tbl25)
				end
			end
		end

		local function slicedfn42()
		end

		-- Moon-style gradient pill button (same wrapper shape as the reference: Button/Gradient/Stroke/Label)
		-- with press feedback and a pulse played whenever its style changes (activation animation)
		local function mkBtn(parent, text, size, pos, anchor, style)
			local U = SourcesLib.UI
			local button = Instance.new("TextButton")
			button.AutoButtonColor = false
			button.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
			button.BackgroundTransparency = 0.05
			button.BorderSizePixel = 0
			button.Text = ""
			button.Size = size
			button.Position = pos or UDim2.new()
			button.AnchorPoint = anchor or Vector2.new(0, 0)
			button.ZIndex = 3
			U.corner(button, 8)
			local liveStroke = U.addLivingStroke(button, 1)
			liveStroke.Color = Color3.fromRGB(255, 255, 255)
			local strokeObj = liveStroke:FindFirstChildOfClass("UIGradient")
			local gradient = Instance.new("UIGradient")
			local lbl = Instance.new("TextLabel")
			lbl.Name = "Label"
			lbl.BackgroundTransparency = 1
			lbl.Size = UDim2.fromScale(1, 1)
			lbl.Font = Enum.Font.GothamBold
			lbl.TextSize = 10
			lbl.TextColor3 = Color3.fromRGB(255, 255, 255)
			lbl.Text = text or ""
			lbl.ZIndex = 4
			lbl.Parent = button
			gradient.Parent = lbl
			local scale = Instance.new("UIScale")
			scale.Parent = button
			button.Parent = parent

			local function bounce(value, time, easing)
				TweenService:Create(scale, TweenInfo.new(time, easing or Enum.EasingStyle.Quad, Enum.EasingDirection.Out), { Scale = value }):Play()
			end

			button.MouseButton1Down:Connect(function()
				bounce(0.92, 0.08)
			end)
			button.MouseButton1Up:Connect(function()
				bounce(1, 0.22, Enum.EasingStyle.Back)
			end)
			button.MouseLeave:Connect(function()
				bounce(1, 0.15)
			end)

			local w = { Button = button, Gradient = gradient, Stroke = strokeObj, Label = lbl }
			w.Pulse = function()
				scale.Scale = 1.14
				bounce(1, 0.38, Enum.EasingStyle.Back)
			end

			if style then
				slicedfn31(w, style)
			end
			return w
		end

		local function slicedfn43(arg)
			local U = SourcesLib.UI
			local row = Instance.new("Frame")
			row.Size = UDim2.new(1, 0, 0, 52)
			row.BackgroundColor3 = U.C.ROW
			row.BackgroundTransparency = 0.15
			row.BorderSizePixel = 0
			U.corner(row, 8)
			U.addLivingStroke(row, 1)

			local rowScale = Instance.new("UIScale")
			rowScale.Scale = 0.9
			rowScale.Parent = row

			local accent = Instance.new("Frame")
			accent.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
			accent.BorderSizePixel = 0
			accent.Position = UDim2.new(0, 4, 0.5, -16)
			accent.Size = UDim2.fromOffset(3, 32)
			accent.ZIndex = 2
			U.corner(accent, 2)
			local accentGradient = Instance.new("UIGradient")
			accentGradient.Rotation = 90
			accentGradient.Parent = accent
			accent.Parent = row

			local iconHolder = Instance.new("Frame")
			iconHolder.BackgroundColor3 = U.C.DEEP1
			iconHolder.BorderSizePixel = 0
			iconHolder.Position = UDim2.new(0, 11, 0.5, -18)
			iconHolder.Size = UDim2.fromOffset(36, 36)
			iconHolder.ZIndex = 2
			U.corner(iconHolder, 9)
			iconHolder.Parent = row

			local icon = Instance.new("ImageLabel")
			icon.BackgroundTransparency = 1
			icon.AnchorPoint = Vector2.new(0.5, 0.5)
			icon.Position = UDim2.fromScale(0.5, 0.5)
			icon.Size = UDim2.fromScale(0.92, 0.92)
			icon.ScaleType = Enum.ScaleType.Fit
			icon.ZIndex = 3
			icon.Parent = iconHolder

			local nameLabel = Instance.new("TextLabel")
			nameLabel.BackgroundTransparency = 1
			nameLabel.Position = UDim2.new(0, 54, 0, 4)
			nameLabel.Size = UDim2.new(1, -60, 0, 14)
			nameLabel.Font = Enum.Font.GothamBold
			nameLabel.TextSize = 11
			nameLabel.TextXAlignment = Enum.TextXAlignment.Left
			nameLabel.TextTruncate = Enum.TextTruncate.AtEnd
			nameLabel.TextColor3 = Color3.fromRGB(255, 255, 255)
			nameLabel.Text = ""
			nameLabel.ZIndex = 2
			nameLabel.Parent = row
			local nameGradient = Instance.new("UIGradient")
			nameGradient.Parent = nameLabel
			if U.Shimmer then U.Shimmer(nameGradient) end

			local valueLabel = Instance.new("TextLabel")
			valueLabel.BackgroundTransparency = 1
			valueLabel.Position = UDim2.new(0, 54, 0, 18)
			valueLabel.Size = UDim2.fromOffset(70, 13)
			valueLabel.Font = Enum.Font.GothamBold
			valueLabel.TextSize = 10
			valueLabel.TextXAlignment = Enum.TextXAlignment.Left
			valueLabel.TextColor3 = Color3.fromRGB(105, 235, 155)
			valueLabel.Text = ""
			valueLabel.ZIndex = 2
			valueLabel.Parent = row

			local detailLabel = Instance.new("TextLabel")
			detailLabel.BackgroundTransparency = 1
			detailLabel.Position = UDim2.new(0, 126, 0, 18)
			detailLabel.Size = UDim2.new(1, -132, 0, 13)
			detailLabel.Font = Enum.Font.GothamMedium
			detailLabel.TextSize = 9
			detailLabel.TextXAlignment = Enum.TextXAlignment.Left
			detailLabel.TextTruncate = Enum.TextTruncate.AtEnd
			detailLabel.TextColor3 = U.C.SILVER2
			detailLabel.Text = ""
			detailLabel.ZIndex = 2
			detailLabel.Parent = row

			local badge = Instance.new("TextLabel")
			badge.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
			badge.BorderSizePixel = 0
			badge.Position = UDim2.new(0, 5, 0, 2)
			badge.Size = UDim2.fromOffset(24, 13)
			badge.Font = Enum.Font.GothamBold
			badge.TextSize = 9.5
			badge.TextColor3 = Color3.fromRGB(0, 10, 20)
			badge.Text = "#1"
			badge.Visible = false
			badge.ZIndex = 6
			U.corner(badge, 6)
			local badgeGradient = Instance.new("UIGradient")
			badgeGradient.Parent = badge
			badge.Parent = row

			local tbl24 = {
				Uid = arg,
				Frame = row,
				Icon = icon,
				Label = nameLabel,
				ValueLabel = valueLabel,
				DetailLabel = detailLabel,
				Gradient = nameGradient,
				AccentGradient = accentGradient,
				Badge = badge,
				BadgeGradient = badgeGradient,
			}

			tbl24.Steal = mkBtn(row, "Steal", UDim2.fromOffset(54, 20), UDim2.new(1, -6, 0, 38), Vector2.new(1, 0.5), tbl14.Steal)
			tbl24.Cancel = mkBtn(row, "X", UDim2.fromOffset(22, 20), UDim2.new(1, -6, 0, 38), Vector2.new(1, 0.5), tbl14.Cancel)
			tbl24.Down = mkBtn(row, "v", UDim2.fromOffset(22, 20), UDim2.new(1, -30, 0, 38), Vector2.new(1, 0.5), tbl14.Hud)
			tbl24.Up = mkBtn(row, "^", UDim2.fromOffset(22, 20), UDim2.new(1, -54, 0, 38), Vector2.new(1, 0.5), tbl14.Hud)
			tbl24.Star = mkBtn(row, "TOP", UDim2.fromOffset(30, 20), UDim2.new(1, -78, 0, 38), Vector2.new(1, 0.5), tbl14.Queued)
			tbl24.Cancel.Button.Visible = false
			tbl24.Down.Button.Visible = false
			tbl24.Up.Button.Visible = false
			tbl24.Star.Label.TextSize = 8.5
			tbl24.Steal.Label.TextSize = 9.5

			for _, sliced20 in ipairs({ { tbl24.Up, -1 }, { tbl24.Down, 1 } }) do
				sliced20[1].Button.Activated:Connect(function()
					if type(tbl4.MoveInPlan) == "function" then
						tbl4.MoveInPlan(tbl24.Uid, sliced20[2])
					end

					tbl4.UiDefer(slicedfn41)
				end)
			end

			tbl24.Steal.Button.Activated:Connect(function()
				if tbl24.Rank == nil and type(tbl4.StealNow) == "function" then
					tbl4.StealNow(tbl24.Uid, false)
				end

				tbl4.UiDefer(slicedfn41)
			end)

			tbl24.Cancel.Button.Activated:Connect(function()
				tbl22[tbl24.Uid] = os.clock() + slicedn18

				if type(tbl4.CancelSteal) == "function" then
					tbl4.CancelSteal(tbl24.Uid)
				end

				tbl4.UiDefer(slicedfn41)
			end)

			tbl24.Star.Button.Activated:Connect(function()
				if type(tbl4.PrioritizeSteal) == "function" then
					tbl4.PrioritizeSteal(tbl24.Uid)
				end

				tbl4.UiDefer(slicedfn41)
			end)

			row.Parent = sliced16
			TweenService:Create(rowScale, TweenInfo.new(0.32, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Scale = 1 }):Play()
			return tbl24
		end

		local function slicedfn44(arg, arg2)
			local style = arg2.Style

			if arg.Category ~= arg2.Category then
				arg.Category = arg2.Category

				if arg.Icon then
					arg.Icon.Image = style.Icon
				end

				if arg.Gradient then
					arg.Gradient.Color = style.GradientColor
					arg.Gradient.Rotation = style.GradientRotation
					if arg.AccentGradient then
						arg.AccentGradient.Color = style.GradientColor
					end
				end
			end

			slicedfn22(arg.Label, style.Name)
			slicedfn22(arg.ValueLabel, slicedfn21(arg2.Value))
			slicedfn22(arg.DetailLabel, arg2.Detail or "")
		end

		local function slicedfn45(arg)
			local slicedn19 = tonumber(arg) or 0
			local str = slicedn19 >= 1000 and string.format("%.0f", slicedn19) or string.format("%.2f", slicedn19)
			local sliced20, sliced21 = string.match(str, "^(%-?%d+)(%.%d+)$")
			sliced20 = sliced20 or str
			local sliced22

			while true do
				local sliced23
				sliced22, sliced23 = string.gsub(sliced20, "^(%-?%d+)(%d%d%d)", "%1,%2")

				if sliced23 == 0 then
					break
				else
					sliced20 = sliced22
				end
			end

			return sliced22 .. (sliced21 or "") .. " Kg"
		end

		local function slicedfn46(arg, arg2)
			local str = string.format("x%.2f", arg2)
			local eggRecords = tbl.EggRecords
			local flag11 = type(eggRecords) == "table" and type(eggRecords.WeightKgForScale) == "function"
			local slicedn19 = 0

			if flag11 then
				local ok, result = pcall(eggRecords.WeightKgForScale, arg, arg2)

				if ok and tonumber(result) then
					slicedn19 = tonumber(result)
					str ..= "  " .. utf8.char(183) .. "  " .. slicedfn45(result)
				end
			end

			return str, slicedn19
		end

		local slicedfn47 = nil

		local function slicedfn48(arg)
			local sliced20 = slicedfn34()

			if sliced20 and arg == slicedn13 and flag4 then
				local tbl24 = {}
				local now = os.clock()
				local slicedn19 = -1
				local sliced21 = nil

				for _, sliced22 in pairs(sliced20) do
					local uid = type(sliced22) == "table" and sliced22.Uid or nil
					local flag11 = sliced22.State == "Slot" or sliced22.State == "Dropped" or sliced22.State == "Carried"

					if type(uid) == "string" and flag11 and type(sliced22.AssetCategory) == "string" then
						tbl24[uid] = true
						local sliced23 = slicedfn19(sliced22.AssetCategory)
						local tbl25 = tbl19[uid]

						if not tbl25 then
							tbl25 = { Uid = uid }
							tbl19[uid] = tbl25
						end

						local scale = tonumber(sliced22.AssetScale) or 1

						if tbl25.Detail == nil or tbl25.Scale ~= scale or tbl25.Category ~= sliced22.AssetCategory then
							tbl25.Scale = scale
							local sliced24, sliced25 = slicedfn46(sliced22.AssetCategory, scale)
							tbl25.Detail = sliced24
							tbl25.Weight = sliced25
						end

						tbl25.Category = sliced22.AssetCategory
						tbl25.Style = sliced23
						tbl25.Value = slicedfn20(sliced22, sliced23)
						tbl25.Position = typeof(sliced22.BottomCFrame) == "CFrame" and sliced22.BottomCFrame.Position or nil

						if (sliced22.State == "Slot" or sliced22.State == "Dropped") and sliced23.Icon ~= "" and tbl25.Value > slicedn19 then
							slicedn19 = tbl25.Value
							sliced21 = tbl25
						end

						if flag6 and sliced16 then
							local sliced24 = tbl18[uid]

							if not sliced24 then
								local sliced25 = slicedfn43(uid)
								tbl18[uid] = sliced25
								sliced24 = sliced25
							end

							slicedfn44(sliced24, tbl25)
						end
					end

					if not (slicedn5 < os.clock() - now) then
						continue
					end
					RunService.Heartbeat:Wait()
					now = os.clock()
					if arg ~= slicedn13 or not flag4 then
						return
					end
				end

				for k in pairs(tbl19) do
					if not tbl24[k] then
						tbl19[k] = nil
						local sliced22 = tbl18[k]

						if sliced22 then
							tbl18[k] = nil
							sliced22.Frame:Destroy()
						end
					end
				end

				if imageLabel and sliced21 and imageLabel.Image ~= sliced21.Style.Icon then
					imageLabel.Image = sliced21.Style.Icon
				elseif imageLabel and not sliced21 then
					imageLabel.Image = ""
				end

				local hero = tbl4.Hero
				if hero and hero.Name and hero.Name.Parent then
					hero.Name.Text = sliced21 and tostring(sliced21.Style.Name) or "None"

					
					hero.Value.Text = sliced21 and slicedfn21(sliced21.Value) or ""
				end

				slicedfn41()
			end
		end

		local slicedn19 = 0

		local function slicedfn49(arg)
			if flag9 and os.clock() - slicedn19 < 10 then
				flag10 = true
				return
			end
			flag9 = true
			slicedn19 = os.clock()
			pcall(slicedfn48, arg)

			if slicedn19 == slicedn19 then
				flag9 = false
			end

			if flag10 then
				flag10 = false
				slicedfn47()
			end
		end

		slicedfn47 = function()
			if flag8 or not flag4 then
				return
			end
			flag8 = true
			local sliced20 = slicedn13

			task.delay(flag6 and 0.3 or 1, function()
				flag8 = false

				if flag4 and sliced20 == slicedn13 then
					task.spawn(pcall, slicedfn49, sliced20)
				end
			end)
		end

		local function slicedfn50(arg)
			if flag6 or not win then
				return
			end
			flag6 = true

			if arg then
				sliced18:Set(true)
			end

			win.SetOpen(true)
			task.spawn(pcall, slicedfn49, slicedn13)
		end

		local function slicedfn51(arg, arg2)
			if not flag6 or not win then
				return
			end
			flag6 = false

			if arg2 then
				sliced18:Set(false)
			end

			win.SetOpen(false)
		end

		local function slicedfn52()
			return true
		end

		local function slicedfn53()
		end

		-- Steal Panel built on the same Moon window + widgets as the Events window
		local function slicedfn54()
			local U = SourcesLib.UI
			win = SourcesLib.NewToolWindow({
				name = "steal",
				tabName = "StealPanel",
				frameName = "SourcesHubSteal",
				title = "Steal Panel",
				tabTitle = "Steal",
				subtitle = "Live egg field",
				w = 262,
				h = 410,
				pos = UDim2.new(1, -274, 0.5, -math.floor(math.min(410, math.max(240, ((workspace.CurrentCamera and workspace.CurrentCamera.ViewportSize.Y) or 600) - 60)) / 2)),
			})
			local tab = win.tab

			-- pinned toolbar: the three things used all the time
			local page = tab.page
			local bar = Instance.new("Frame")
			bar.Name = "Bar"
			bar.BackgroundTransparency = 1
			bar.Size = UDim2.new(1, 0, 0, 82)
			bar.Position = UDim2.new(0, 0, 0, 66)
			bar.Parent = win.content
			page.Position = UDim2.new(0, 0, 0, 148)
			page.Size = UDim2.new(1, 0, 1, -148)

			-- hero card: picture of the strongest egg on the field right now
			local hero = Instance.new("Frame")
			hero.Name = "Hero"
			hero.BackgroundColor3 = U.C.ROW
			hero.BackgroundTransparency = 0.15
			hero.BorderSizePixel = 0
			hero.Position = UDim2.new(0, 8, 0, 4)
			hero.Size = UDim2.new(1, -16, 0, 58)
			U.corner(hero, 12)
			U.addLivingStroke(hero, 1)
			hero.Parent = win.content
			local heroIcon = Instance.new("ImageLabel")
			heroIcon.BackgroundTransparency = 1
			heroIcon.Position = UDim2.new(0, 6, 0, 3)
			heroIcon.Size = UDim2.fromOffset(52, 52)
			heroIcon.ScaleType = Enum.ScaleType.Fit
			heroIcon.Image = ""
			heroIcon.Parent = hero
			local heroTag = U.label(hero, "STRONGEST EGG", UDim2.new(1, -70, 0, 12), U.C.SILVER, Enum.Font.GothamBold)
			heroTag.Position = UDim2.new(0, 64, 0, 6)
			heroTag.TextSize = 8.5
			local heroName = U.label(hero, "None", UDim2.new(1, -70, 0, 18), U.C.WHITE, Enum.Font.GothamBold)
			heroName.Position = UDim2.new(0, 64, 0, 19)
			heroName.TextSize = 13
			heroName.TextTruncate = Enum.TextTruncate.AtEnd
			local heroValue = U.label(hero, "", UDim2.new(1, -70, 0, 14), Color3.fromRGB(105, 235, 155), Enum.Font.GothamBold)
			heroValue.Position = UDim2.new(0, 64, 0, 38)
			heroValue.TextSize = 11
			imageLabel = heroIcon
			tbl4.Hero = { Name = heroName, Value = heroValue }

			local function makeSwitchButton(text, pos, onChange)
				local btn = mkBtn(bar, text .. ": OFF", UDim2.new(0.5, -11, 0, 26), pos, nil, tbl14.Queued)
				btn.Label.TextSize = 10
				local obj = { State = false }

				function obj:Set(v)
					v = v == true

					if v == self.State then
						return
					end
					self.State = v
					slicedfn31(btn, v and tbl14.Steal or tbl14.Queued)
					btn.Label.Text = text .. (v and ": ON" or ": OFF")
				end

				btn.Button.Activated:Connect(function()
					onChange(not obj.State)
				end)

				return obj
			end

			local toggleHandle = makeSwitchButton("Auto Steal", UDim2.new(0, 8, 0, 4), function(v)
				local handle = sliced5

				if handle and type(handle.Set) == "function" then
					pcall(handle.Set, handle, v == true)
				end

				tbl4.UiDefer(slicedfn40)
			end)

			local modeButton = mkBtn(bar, "Mode: Normal", UDim2.new(0, 112, 0, 22), UDim2.new(0, 8, 0, 35), nil, tbl14.Queued)
			modeButton.Label.TextSize = 8.5
			modeButton.Label.TextTruncate = Enum.TextTruncate.AtEnd

			-- small guide badge: shows the current mode and says it is edited with the Mode button next to it
			local modeBadge = Instance.new("Frame")
			modeBadge.Name = "ModeBadge"
			modeBadge.BackgroundColor3 = U.C.ROW
			modeBadge.BackgroundTransparency = 0.15
			modeBadge.BorderSizePixel = 0
			modeBadge.Position = UDim2.new(0, 126, 0, 35)
			modeBadge.Size = UDim2.new(1, -162, 0, 22)
			U.corner(modeBadge, 11)
			U.addLivingStroke(modeBadge, 1.2)
			modeBadge.Parent = bar
			local modeBadgeTitle = U.label(modeBadge, "Normal", UDim2.new(1, -10, 0, 11), U.C.WHITE, Enum.Font.GothamBold, Enum.TextXAlignment.Center)
			modeBadgeTitle.Position = UDim2.new(0, 5, 0, 1)
			modeBadgeTitle.TextSize = 9
			modeBadgeTitle.TextTruncate = Enum.TextTruncate.AtEnd
			U.liveGrad(modeBadgeTitle)
			local modeBadgeHint = U.label(modeBadge, "< editable with Mode", UDim2.new(1, -10, 0, 9), U.C.SILVER2, Enum.Font.GothamMedium, Enum.TextXAlignment.Center)
			modeBadgeHint.Position = UDim2.new(0, 5, 0, 11)
			modeBadgeHint.TextSize = 7

			local function layoutMode()
				if modeBadge.Visible then
					modeButton.Button.Size = UDim2.new(0, 112, 0, 22)
				else
					modeButton.Button.Size = UDim2.new(1, -46, 0, 22)
				end
			end

			local function hideGuide()
				modeBadge.Visible = false
				layoutMode()
				SourcesLib.MarkGuideSeen()
			end

			-- "?" stays available for everyone and opens a short explanation of the delivery system
			local helpButton = mkBtn(bar, "?", UDim2.fromOffset(24, 22), UDim2.new(1, -32, 0, 35), nil, tbl14.Hud)
			helpButton.Label.TextSize = 11
			local guideCard = Instance.new("Frame")
			guideCard.Name = "DeliveryGuide"
			guideCard.BackgroundColor3 = U.C.BG
			guideCard.BackgroundTransparency = 0.12
			guideCard.BorderSizePixel = 0
			guideCard.Position = UDim2.new(0, 8, 0, 4)
			guideCard.Size = UDim2.new(1, -16, 1, -8)
			guideCard.ZIndex = 90
			guideCard.Visible = false
			U.corner(guideCard, 12)
			U.addLivingStroke(guideCard, 1.5)
			guideCard.Parent = win.content
			local guideScroll = Instance.new("ScrollingFrame")
			guideScroll.BackgroundTransparency = 1
			guideScroll.BorderSizePixel = 0
			guideScroll.Position = UDim2.new(0, 6, 0, 6)
			guideScroll.Size = UDim2.new(1, -12, 1, -44)
			guideScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
			guideScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
			guideScroll.ScrollBarThickness = 3
			guideScroll.ScrollBarImageColor3 = U.C.MOON
			guideScroll.ZIndex = 91
			guideScroll.Parent = guideCard
			local guideText = U.label(guideScroll, "", UDim2.new(1, -8, 0, 0), U.C.SILVER, Enum.Font.GothamMedium)
			guideText.AutomaticSize = Enum.AutomaticSize.Y
			guideText.TextWrapped = true
			guideText.RichText = true
			guideText.TextSize = 10
			guideText.TextYAlignment = Enum.TextYAlignment.Top
			guideText.ZIndex = 92
			guideText.Text = "<b>HOW DELIVERY WORKS</b>\n"
				.. "<b>Normal</b>: you carry the egg home on foot. Slowest, but the least risky.\n"
				.. "<b>Instant TP</b>: you hop to the line, put the egg down, take it back, then cross. Fast.\n"
				.. "<b>Delivery Stop</b>: the same trip with pauses (Delivery Steps). Slower, safer.\n\n"
				.. "<b>RISKS</b>\n"
				.. "- Above 115% speed the server rejects the delivery or pulls you back.\n"
				.. "- A guard hit can send the egg back to its nest.\n"
				.. "- Fewer Delivery Steps is faster but works less often.\n"
				.. "- Keep Anti Guard on to slip past the guard when you grab the egg."
			local guideClose = mkBtn(guideCard, "Got it", UDim2.new(1, -16, 0, 24), UDim2.new(0, 8, 1, -30), nil, tbl14.Steal)
			guideClose.Label.TextSize = 10

			local function openGuide()
				guideCard.Visible = true
				page.ScrollingEnabled = false
			end

			local function closeGuide()
				guideCard.Visible = false
				page.ScrollingEnabled = true
				hideGuide()
			end

			helpButton.Button.Activated:Connect(openGuide)
			guideClose.Button.Activated:Connect(closeGuide)
			local badgeTap = Instance.new("TextButton")
			badgeTap.BackgroundTransparency = 1
			badgeTap.Text = ""
			badgeTap.Size = UDim2.new(1, 0, 1, 0)
			badgeTap.ZIndex = 5
			badgeTap.Parent = modeBadge
			badgeTap.Activated:Connect(openGuide)

			if SourcesLib.GuideSeen() then
				modeBadge.Visible = false
			else
				task.delay(40, hideGuide)
			end
			layoutMode()
			local modeStyles = { Normal = tbl14.Queued, ["Instant TP"] = tbl14.Steal, ["Delivery Stop"] = tbl14.PriorityOn }
			local guardHandle = { Name = "Normal" }

			function guardHandle:Set(name)
				if not modeStyles[name] then
					return
				end
				self.Name = name
				slicedfn31(modeButton, modeStyles[name])
				modeButton.Label.Text = "Mode: " .. name
			end

			-- Mode opens a small card of option chips: "Deliver" (how the egg gets home) and "Go" (how you reach it)
			local branch = nil
			local branchButtons = {}

			local function refreshBranch()
				for _, entry in ipairs(branchButtons) do
					slicedfn31(entry.Button, entry.Name == entry.Group.Current() and tbl14.Steal or tbl14.Queued)
				end
			end

			modeButton.Button.Activated:Connect(function()
				hideGuide()
				if not branch then
					local groups = {
						{ Title = "DELIVER", Names = tbl4.Method.Names, Current = tbl4.Method.Current, Apply = tbl4.Method.Apply },
						{ Title = "GO METHOD", Names = tbl4.GoMethod.Names, Current = tbl4.GoMethod.Current, Apply = tbl4.GoMethod.Apply },
					}
					local total = 8

					for _, group in ipairs(groups) do
						total += 22 + math.ceil(#group.Names / 2) * 26
					end

					branch = Instance.new("ScrollingFrame")
					branch.Name = "ModeBranch"
					branch.CanvasSize = UDim2.new(0, 0, 0, total)
					branch.ScrollBarThickness = 3
					branch.ScrollBarImageColor3 = U.C.MOON
					branch.ScrollingDirection = Enum.ScrollingDirection.Y
					branch.BackgroundColor3 = U.C.BG
					branch.BackgroundTransparency = 0.05
					branch.BorderSizePixel = 0
					branch.Position = UDim2.new(0, 8, 0, 126)
					branch.Size = UDim2.new(1, -16, 0, math.min(total, 170))
					branch.Active = true
					branch.ScrollingEnabled = true
					branch.ZIndex = 60
					branch.Visible = false
					U.corner(branch, 8)
					U.addLivingStroke(branch, 1)
					branch.Parent = win.content

					local cursor = 6

					for _, group in ipairs(groups) do
						local title = U.label(branch, group.Title, UDim2.new(1, -16, 0, 14), U.C.MOON2, Enum.Font.GothamBold)
						title.Position = UDim2.new(0, 10, 0, cursor)
						title.TextSize = 9
						cursor += 18

						for i, name in ipairs(group.Names) do
							local col = (i - 1) % 2
							local y = cursor + math.floor((i - 1) / 2) * 26
							local optionButton = mkBtn(branch, name, UDim2.new(0.5, -11, 0, 22),
								UDim2.new(col == 0 and 0 or 0.5, col == 0 and 8 or 3, 0, y), nil, tbl14.Queued)
							optionButton.Label.TextSize = 9.5
							optionButton.Label.TextTruncate = Enum.TextTruncate.AtEnd
							branchButtons[#branchButtons + 1] = { Button = optionButton, Name = name, Group = group }
							optionButton.Button.Activated:Connect(function()
								group.Apply(name)
								refreshBranch()
								tbl4.UiDefer(slicedfn40)
							end)
						end
						cursor += math.ceil(#group.Names / 2) * 26 + 4
					end
				end

				branch.Visible = not branch.Visible
				page.ScrollingEnabled = not branch.Visible
				refreshBranch()
			end)

			local slicedn29 = 0

			local function cycleSort()
				if os.clock() - slicedn29 < 0.25 then
					return
				end
				slicedn29 = os.clock()
				local sliced25 = tbl5[(table.find(tbl5, sliced4) or 4) % #tbl5 + 1]
				local priorityHandle = tbl4.Steal.PriorityHandle

				if priorityHandle and type(priorityHandle.Set) == "function" then
					pcall(priorityHandle.Set, priorityHandle, sliced25)
				end

				if sliced4 ~= sliced25 then
					sliced4 = sliced25

					if type(tbl4.ResortSteal) == "function" then
						tbl4.ResortSteal()
					end
				end

				tbl4.UiDefer(function()
					slicedfn40()
					slicedfn41()
				end)
			end

			local sortButton = mkBtn(bar, "Sort: " .. tostring(sliced4), UDim2.new(0.5, -11, 0, 26), UDim2.new(0.5, 3, 0, 4), nil, tbl14.Hud)
			sortButton.Label.TextSize = 9
			sortButton.Label.TextTruncate = Enum.TextTruncate.AtEnd
			sortButton.Button.Activated:Connect(function()
				sortButton.Pulse()
				cycleSort()
			end)
			local sortHandle = {
				SetText = function(t)
					sortButton.Label.Text = "Sort: " .. tostring(t)
				end,
			}

			-- trip strip: what the delivery is doing right now
			local strip = Instance.new("Frame")
			strip.Name = "Strip"
			strip.BackgroundTransparency = 1
			strip.Position = UDim2.new(0, 8, 0, 62)
			strip.Size = UDim2.new(1, -16, 0, 16)
			strip.Parent = bar

			local guardDot = Instance.new("Frame")
			guardDot.Position = UDim2.new(0, 0, 0.5, -3)
			guardDot.Size = UDim2.fromOffset(7, 7)
			guardDot.BackgroundColor3 = U.C.DIM
			guardDot.BorderSizePixel = 0
			U.corner(guardDot, 4)
			guardDot.Parent = strip

			local guardText = U.label(strip, "AG", UDim2.fromOffset(20, 16), U.C.DIM, Enum.Font.GothamBold)
			guardText.Position = UDim2.new(0, 11, 0, 0)
			guardText.TextSize = 9

			local phaseText = U.label(strip, "Idle", UDim2.fromOffset(92, 16), U.C.SILVER, Enum.Font.GothamMedium)
			phaseText.Position = UDim2.new(0, 34, 0, 0)
			phaseText.TextSize = 9
			phaseText.TextTruncate = Enum.TextTruncate.AtEnd

			local track = Instance.new("Frame")
			track.BackgroundColor3 = U.C.DEEP1
			track.BorderSizePixel = 0
			track.Position = UDim2.new(0, 130, 0.5, -3)
			track.Size = UDim2.new(1, -130, 0, 6)
			U.corner(track, 3)
			track.Parent = strip

			local fill = Instance.new("Frame")
			fill.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
			fill.BorderSizePixel = 0
			fill.Size = UDim2.new(0, 0, 1, 0)
			U.corner(fill, 3)
			local fillGradient = Instance.new("UIGradient")
			fillGradient.Color = ColorSequence.new(U.C.DEEP3, U.C.MOON2)
			fillGradient.Parent = fill
			fill.Parent = track

			local ticks = {}

			for i = 1, 6 do
				local tick = Instance.new("Frame")
				tick.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
				tick.BackgroundTransparency = 0.3
				tick.BorderSizePixel = 0
				tick.Size = UDim2.fromOffset(2, 10)
				tick.AnchorPoint = Vector2.new(0.5, 0.5)
				tick.Visible = false
				tick.ZIndex = 3
				tick.Parent = track
				ticks[i] = tick
			end

			local shownStops = -1

			local function updateStrip()
				local now = os.clock()
				local trip = tbl4.Trip
				local fresh = trip ~= nil and now - (trip.At or 0) < 1.5
				local text = "Idle"
				local progress = 0
				local stops = 0

				if fresh and (trip.Phase == "Hopping" or trip.Phase == "Stop") then
					stops = trip.Stops or 0
					progress = trip.Progress or 0

					if trip.Phase == "Stop" then
						text = string.format("Step %d/%d done", trip.Stop or 0, stops)
					elseif stops > 1 then
						text = string.format("Hopping, step %d/%d", trip.Stop or 1, stops)
					else
						text = "Hopping"
					end
				elseif tbl4.Steal.Carrying then
					text = "Carrying the egg"
				elseif tbl4.Steal.Active then
					text = "Going to the egg"
				end

				if stops ~= shownStops then
					shownStops = stops

					for i, tick in ipairs(ticks) do
						tick.Visible = i <= stops - 1
						tick.Position = UDim2.new(i / math.max(stops, 1), 0, 0.5, 0)
					end
				end

				phaseText.Text = text
				modeBadgeTitle.Text = tostring(tbl4.Method.Current()) .. " | " .. tostring(tbl4.GoMethod.Current())
				fill.Size = UDim2.new(math.clamp(progress, 0, 1), 0, 1, 0)


				local guard = tbl4.AntiGuard
				local running = guard.Busy == true
				guardDot.BackgroundColor3 = running and Color3.fromRGB(255, 200, 60) or (guard.Enabled and U.C.MOON or U.C.DIM)
				guardText.TextColor3 = running and Color3.fromRGB(255, 200, 60) or (guard.Enabled and U.C.MOON2 or U.C.DIM)
			end

			local stripWin = win
			task.spawn(function()
				while flag4 and win == stripWin and stripWin.frame.Parent do
					task.wait(0.2)

					if flag6 then
						pcall(updateStrip)
					end
				end
			end)

			local speed = tab:CreateSection({ Name = "Speed", Expanded = false })

			local function linkSlider(name, minV, maxV, handle, unit, fallback)
				local start = fallback or 100

				if handle and type(handle.Get) == "function" then
					local ok, v = pcall(handle.Get, handle)
					start = ok and tonumber(v) or start
				end

				local mine
				mine = speed:CreateSlider({
					Name = name,
					Min = minV,
					Max = maxV,
					Default = start,
					Increment = 1,
					Unit = unit or "%",
					Callback = function(v)
						if flagReady and handle and type(handle.Set) == "function" then
							pcall(handle.Set, handle, v, true)
						end
					end,
				})

				if handle and type(handle.Subscribe) == "function" then
					local ok, connection = pcall(handle.Subscribe, handle, function(v)
						mine:Set(v, false)
					end)

					if ok and connection then
						table.insert(tbl20, connection)
					end
				end

				mine:Set(start, false)
				return mine
			end

			linkSlider("Go Speed", 50, 115, tbl4.SafeCarry.RunHandle)
			linkSlider("Carry Speed", 80, 115, tbl4.SafeCarry.CarryHandle)
			linkSlider("Delivery Steps", 1, 6, tbl4.SafeCarry.StopsHandle, "", 3)
			

			local eggs = tab:CreateSection({ Name = "Field Eggs", Expanded = true })
			local list = Instance.new("Frame")
			list.Name = "EggList"
			list.BackgroundTransparency = 1
			list.Size = UDim2.new(1, -6, 0, 0)
			list.AutomaticSize = Enum.AutomaticSize.Y
			list.LayoutOrder = 1
			list.Parent = eggs.body
			local layout = Instance.new("UIListLayout")
			layout.Padding = UDim.new(0, 4)
			layout.SortOrder = Enum.SortOrder.LayoutOrder
			layout.Parent = list

			local emptyLabel = U.label(list, "No eggs on the field", UDim2.new(1, 0, 0, 28), U.C.DIM, Enum.Font.GothamMedium, Enum.TextXAlignment.Center)
			emptyLabel.TextSize = 10.5
			emptyLabel.LayoutOrder = -1

			local function refreshEmpty()
				local count = 0

				for _, child in ipairs(list:GetChildren()) do
					if child:IsA("Frame") then
						count += 1
					end
				end

				emptyLabel.Visible = count == 0
			end

			table.insert(tbl20, list.ChildAdded:Connect(function()
				task.defer(refreshEmpty)
			end))
			table.insert(tbl20, list.ChildRemoved:Connect(function()
				task.defer(refreshEmpty)
			end))

			tbl16 = { ToggleHandle = toggleHandle, GuardHandle = guardHandle, SortHandle = sortHandle }

			tbl4.StealPanelSync = function()
				tbl4.UiDefer(slicedfn40)
			end

			title = win.title
			sliced16 = list
			sliced14 = win.frame
			sliced13 = win.frame
			position = win.frame.Position
			tbl17 = {}

			win.OnClose.Connect(function(on)
				if on == true then
					slicedfn50(true)
				else
					slicedfn51(true, true)
				end
			end)

			refreshEmpty()
			return true
		end

		local function slicedfn55()
			if not flag4 then
				return
			end
			flag4 = false
			slicedn13 += 1
			flag8 = false
			flag10 = false

			if flag6 then
				flag6 = false

				if not slicedfn35() then
					slicedfn37(false, true)
				end
			end

			if tween then
				tween:Cancel()
				tween = nil
			end

			tbl6.DisconnectAll(tbl20)
			table.clear(tbl18)
			table.clear(tbl19)

			if sliced13 then
				sliced13:Destroy()
			end

			if sliced17 then
				sliced17:Destroy()
			end

			sliced13 = nil
			sliced14 = nil
			win = nil
			position = nil
			title = nil
			sliced15 = nil
			sliced16 = nil
			sliced17 = nil
			slicedn14 = 0
			tbl16 = nil
			tbl17 = nil
			slicedn15 = 1
			sliced10 = nil
		end

		slicedfn23 = function()
			if flag4 then
				return
			end

			sliced10 = {}
			flag4 = true
			slicedn13 += 1
			local sliced23 = slicedn13

			if not slicedfn54() then
				slicedfn55()
				return
			end

			if flag7 then
				flag7 = false
				task.spawn(slicedfn50)
			end

			table.insert(tbl20, sliced18:Subscribe(function(on)
				if not flag4 or sliced23 ~= slicedn13 then
					return
				end

				if on == true then
					slicedfn50(false)
				else
					slicedfn51(false, false)
				end
			end))

			local eggState = tbl.EggState

			if type(eggState) == "table" then
				for _, sliced24 in ipairs({ "FieldRefreshed", "FieldShifted", "FieldGone", "FieldClaimed", "SnapshotRefreshed" }) do
					local sliced25 = eggState[sliced24]

					if type(sliced25) == "table" and type(sliced25.Connect) == "function" then
						local ok, result = pcall(sliced25.Connect, sliced25, slicedfn47)

						if ok and result then
							table.insert(tbl20, result)
						end
					end
				end
			end

			local areaEggSlotsClient = workspace:FindFirstChild("AreaEggSlotsClient")

			if areaEggSlotsClient then
				table.insert(tbl20, areaEggSlotsClient.ChildAdded:Connect(slicedfn47))
				table.insert(tbl20, areaEggSlotsClient.ChildRemoved:Connect(slicedfn47))
			end

			-- the panel only works while it is open; a closed panel costs nothing
			task.spawn(function()
				local slicedn20 = 0

				while flag4 and sliced23 == slicedn13 do
					slicedn20 += task.wait(0.5)

					if not flag4 or sliced23 ~= slicedn13 then
						break
					end

					if not (win and win.frame and win.frame.Parent) then
						task.defer(function()
							slicedfn55()

							if tbl4.Toggle(nil, true) then
								slicedfn23()
							end
						end)

						break
					end

					if flag6 then
						if slicedn20 >= slicedn4 then
							slicedfn47()
							slicedn20 = 0
						else
							slicedfn41()
						end
					end
				end
			end)

			task.spawn(pcall, slicedfn49, sliced23)
		end

		slicedfn4(function()
			slicedfn55()

			if sliced11 then
				sliced11:Destroy()
			end

			slicedfn33(nil)
			sliced11 = nil
			sliced12 = nil
			imageLabel = nil
		end)

		tbl4.RestoreStealPanel = function()
			flagReady = true

			local methodHandle = tbl4.SafeCarry.MethodHandle
			local savedMode = methodHandle and type(methodHandle.Get) == "function" and methodHandle.Get() or "Delivery Stop"
			tbl4.Method.Apply(savedMode)
			tbl4.MethodReady = true
			if sliced18:Get() ~= true then
				return
			end

			if flag4 and sliced13 and not flag6 then
				task.spawn(slicedfn50)
			else
				flag7 = true
			end
		end
	end

	task.defer(slicedfn23)

	do
		local sliced19 = sliced2:CreateTab({ Name = "Predictor", SectionsExpanded = true })
		sliced6 = sliced19:CreateSection({ Name = "Discord Webhook", Expanded = false })
		sliced7 = sliced19:CreateSection({ Name = "Egg Predictor", Expanded = true })
		sliced8 = sliced19:CreateSection({ Name = "Fuse Predictor", Expanded = false })

		local function slicedfn34(arg, arg2)
			local ok, result = pcall(Font.new, arg, arg2, Enum.FontStyle.Normal)
			return ok and result or nil
		end

		tbl7 = {
			Ready = type(sliced7.CreateCanvas) == "function",
			Bullet = utf8.char(8226),
			Color = {
				Text = "#FFFFFF",
				Income = "#4DFF7A",
				Clock = "#FFC24D",
				Ready = "#4DFF7A",
				Growing = "#FFC24D",
				Inventory = "#7FD8FF",
				Weight = "#CDE7FF",
				Scale = "#FFDF8A",
				Separator = "#7A8CC0",
				Hint = "#9FB8FF",
			},
			NameFont = slicedfn34("rbxasset://fonts/families/GothamSSm.json", Enum.FontWeight.ExtraBold),
		}

		tbl7.RarityFont = slicedfn34("rbxassetid://12187365977", Enum.FontWeight.Bold) or slicedfn34("rbxasset://fonts/families/FredokaOne.json", Enum.FontWeight.Regular)
		local sequence2 = tbl6.Sequence
		local tbl22 = {}
		local tbl23 = { 0, Color3.fromRGB(255, 255, 255) }
		local tbl24 = { 0.5, Color3.fromRGB(222, 238, 255) }
		local tbl25 = { 1, Color3.fromRGB(255, 255, 255) }
		tbl22[1] = tbl23
		tbl22[2] = tbl24
		tbl22[3] = tbl25
		tbl7.NameGradient = sequence2(tbl22)
		local sequence3 = tbl6.Sequence
		local tbl26 = {}
		local tbl27 = { 0, Color3.fromRGB(255, 255, 255) }
		local tbl28 = { 0.2, Color3.fromRGB(206, 212, 224) }
		local tbl29 = { 0.42, Color3.fromRGB(74, 80, 94) }
		local tbl30 = { 0.58, Color3.fromRGB(42, 46, 56) }
		local tbl31 = { 0.78, Color3.fromRGB(158, 166, 182) }
		local tbl32 = { 1, Color3.fromRGB(250, 252, 255) }
		tbl26[1] = tbl27
		tbl26[2] = tbl28
		tbl26[3] = tbl29
		tbl26[4] = tbl30
		tbl26[5] = tbl31
		tbl26[6] = tbl32
		tbl7.SecretGradient = sequence3(tbl26)
		tbl7.SecretRotation = 90

		tbl7.Paint = function(arg, arg2)
			return string.format("<font color=\"%s\">%s</font>", arg, arg2)
		end

		tbl7.Bold = function(arg)
			return "<b>" .. tostring(arg) .. "</b>"
		end

		tbl7.Escape = function(arg)
			return (string.gsub(tostring(arg), "[<>&]", { ["<"] = "&lt;", [">"] = "&gt;", ["&"] = "&amp;" }))
		end

		tbl7.Separator = function()
			return tbl7.Paint(tbl7.Color.Separator, "  " .. tbl7.Bullet .. "  ")
		end

		tbl7.FormatRate = function(arg)
			local slicedn16 = tonumber(arg) or 0
			if slicedn16 >= 1e12 then
				return string.format("%.2fT/s", slicedn16 / 1e12)
			end

			if slicedn16 >= 1e9 then
				return string.format("%.2fB/s", slicedn16 / 1e9)
			end

			if slicedn16 >= 1000000 then
				return string.format("%.2fM/s", slicedn16 / 1000000)
			end

			if slicedn16 >= 1000 then
				return string.format("%.1fK/s", slicedn16 / 1000)
			end
			return string.format("%d/s", math.floor(slicedn16))
		end

		tbl7.FormatWeight = function(arg)
			local slicedn16 = tonumber(arg) or 0
			local str = slicedn16 >= 1000 and string.format("%.0f", slicedn16) or string.format("%.2f", slicedn16)
			local sliced20, sliced21 = string.match(str, "^(%-?%d+)(%.%d+)$")
			sliced20 = sliced20 or str
			local sliced22

			while true do
				local sliced23
				sliced22, sliced23 = string.gsub(sliced20, "^(%-?%d+)(%d%d%d)", "%1,%2")

				if sliced23 ~= 0 then
					sliced20 = sliced22
				else
					break
				end
			end

			return sliced22 .. (sliced21 or "") .. " Kg"
		end

		tbl7.FormatClock = function(arg)
			local slicedn16 = math.max(0, math.floor(tonumber(arg) or 0))
			return string.format("%02dh %02dm %02ds", math.floor(slicedn16 / 3600), math.floor(slicedn16 % 3600 / 60), slicedn16 % 60)
		end

		tbl7.ScaleFactor = function(arg)
			if arg > 5 then
				return (arg / 5) ^ 1.2 * 19.637875755794113
			end
			return arg ^ 1.85
		end

		tbl7.MutationMultiplier = function(arg)
			arg = type(arg) == "table" and arg or {}
			local mutations = tbl.Mutations

			if type(mutations) == "table" and type(mutations.EarningsFor) == "function" then
				local ok, result = pcall(mutations.EarningsFor, arg)
				if ok and type(result) == "number" then
					return result
				end
			end

			return 1
		end

		local tbl33 = {
			Golden = "#FFD34D",
			Silver = "#E6EEF7",
			Sakura = "#FF9ED8",
			GreatBloom = "#7CFFC4",
			Boss = "#FF7A7A",
			Monstrous = "#C08BFF",
		}

		local tbl34 = { "#FF6B6B", "#FFB36B", "#FFF06B", "#6BFF8A", "#6BC8FF", "#B96BFF" }

		tbl7.MutationText = function(arg)
			local tbl35 = {}

			if type(arg) == "table" then
				for _, sliced20 in ipairs(arg) do
					local sliced21 = string.upper(slicedfn7(sliced20))

					if sliced20 == "Rainbow" or sliced20 == "Prismatic" then
						local tbl36 = {}

						for i = 1, #sliced21 do
							table.insert(tbl36, tbl7.Paint(tbl34[(i - 1) % #tbl34 + 1], string.sub(sliced21, i, i)))
						end

						table.insert(tbl35, tbl7.Bold(table.concat(tbl36)))
					else
						table.insert(tbl35, tbl7.Bold(tbl7.Paint(tbl33[sliced20] or "#8FE3FF", tbl7.Escape(sliced21))))
					end
				end
			end

			return table.concat(tbl35, " ")
		end

		local rarityGradients = nil

		local function slicedfn35(arg)
			if type(arg) == "table" and typeof(arg.RarityGradient) == "Instance" then
				return arg.RarityGradient
			end

			if rarityGradients == nil then
				local assets = ReplicatedStorage:FindFirstChild("Assets")
				assets = assets and assets:FindFirstChild("UI")
				rarityGradients = assets and assets:FindFirstChild("RarityGradients") or false
			end

			if not rarityGradients or type(arg) ~= "table" then
				return nil
			end
			local sliced20 = rarityGradients:FindFirstChild(tostring(arg._id or arg.DisplayName or ""))
			return sliced20 and sliced20:FindFirstChild("RarityGradient") or nil
		end

		local tbl35 = {}

		tbl7.AssetInfo = function(arg)
			local category = tostring(arg)
			local sliced20 = tbl35[category]
			if sliced20 then
				return sliced20
			end
			local directory = tbl.Assets and tbl.Assets.Directory
			local flag11 = type(directory) == "table" and directory[category] or nil

			if flag11 == nil and type(directory) == "table" then
				local sliced21 = string.gsub(string.lower(category), "[^%a%d]", "")

				for k, sliced22 in pairs(directory) do
					if type(sliced22) == "table" then
						local tbl36 = {}
						local str = tostring(k)
						local str2 = tostring(sliced22._id or "")
						local tostring = tostring
						local displayName = sliced22.DisplayName or ""
						local sliced24 = table.pack(tostring(displayName))
						tbl36[1] = str
						tbl36[2] = str2

						do
							local values = table.pack(table.unpack(sliced24, 1, sliced24.n))
							table.move(values, 1, values.n, 3, tbl36)
						end

						local egg = type(sliced22.Egg) == "table" and sliced22.Egg or nil

						if egg ~= nil then
							tbl36[#tbl36 + 1] = tostring(egg.ModelName or "")
						end

						for _, sliced25 in ipairs(tbl36) do
							if sliced25 ~= "" and string.gsub(string.lower(sliced25), "[^%a%d]", "") == sliced21 then
								flag11 = sliced22
								break
							end
						end
					end

					if flag11 == nil then
						continue
					end
					break
				end
			end

			local rarity = type(flag11) == "table" and type(flag11.Rarity) == "table" and flag11.Rarity or nil
			local icon = type(flag11) == "table" and flag11.Icon or nil
			local rarity2

			if rarity then
				rarity2 = tostring(rarity.DisplayName or rarity._id or "Common")
			else
				rarity2 = rarity
			end

			rarity2 = rarity2 or "Common"
			local color4 = rarity and typeof(rarity.Color) == "Color3" and rarity.Color or Color3.fromRGB(255, 255, 255)
			local tbl36 = {}
			local name = type(flag11) == "table"

			if name then
				name = tostring(flag11.DisplayName or category)
			end

			tbl36.Name = name or category
			tbl36.Category = category
			tbl36.Rarity = rarity2
			local rarityNumber

			if rarity then
				rarityNumber = tonumber(rarity.RarityNumber or rarity.Rank)
			else
				rarityNumber = rarity
			end

			tbl36.RarityNumber = rarityNumber or 0
			tbl36.Color = color4
			tbl36.Hex = "#" .. string.upper(color4:ToHex())
			tbl36.Gradient = slicedfn35(rarity)
			tbl36.EarningRate = type(flag11) == "table" and tonumber(flag11.EarningRate) or 0
			tbl36.Icon = type(icon) == "string" and icon ~= "" and icon or nil
			tbl35[category] = tbl36
			return tbl36
		end

		tbl7.Income = function(arg, arg2, arg3)
			if type(arg2) ~= "number" or arg2 <= 0 then
				return 0
			end
			return math.max(math.round(arg.EarningRate * tbl7.ScaleFactor(arg2) * tbl7.MutationMultiplier(arg3)), 1)
		end

		local function isShown(arg)
			if typeof(arg) ~= "Instance" or not arg:IsDescendantOf(game) then
				return false
			end

			while arg do
				if arg:IsA("GuiObject") and not arg.Visible then
					return false
				end

				if arg:IsA("LayerCollector") then
					return arg.Enabled
				end
				arg = arg.Parent
			end

			return false
		end

		tbl7.PageVisible = function()
			local ok, result = pcall(function()
				return sliced19.Page
			end)

			if not ok or typeof(result) ~= "Instance" then
				return true
			end
			return isShown(result) and result.AbsoluteSize.X > 0
		end

		tbl7.IsShown = isShown
	end

	tbl8 = { "Value", "Rarity", "Time Left" }

	tbl9 = {
		{ Key = "Ready", Title = "READY TO HATCH", Color = tbl7.Color.Ready },
		{ Key = "Growing", Title = "GROWING", Color = tbl7.Color.Growing },
		{ Key = "Inventory", Title = "IN INVENTORY", Color = tbl7.Color.Inventory },
	}

	n = 1
	paint = tbl7.Paint
	bold = tbl7.Bold
	color2 = tbl7.Color
	tbl10 = { Sort = tbl8[1], Spotlight = true }
	id = nil
	local slicedn16 = 0.0909
	sliced9 = nil
	local tbl22 = {}
	tbl11 = {}
	tbl12 = {}
	tbl13 = {}
	local slicedn17 = 0
	local slicedn18 = 0
	local slicedn19 = 0.06
	local slicedn20 = -1
	local slicedn21 = -1
	local slicedn22 = -1
	local slicedn23 = 4
	local slicedn24 = 3
	flag = false
	slicedn2 = 0
	flag2 = true
	slicedn3 = 0
	flag3 = false
	local sliced19 = nil

	requestEggRefresh = function()
		flag2 = true
	end

	do
		local function slicedfn34(arg)
			if not arg or arg.DiffWrapped then
				return arg
			end
			local set = arg.Set
			arg.DiffWrapped = true

			arg.Set = function(arg2)
				if type(arg2) ~= "table" then
					return set(arg2)
				end
				local spec = arg.Spec
				local tbl23 = nil

				for k, sliced20 in pairs(arg2) do
					if spec[k] ~= sliced20 then
						tbl23 = tbl23 or {}
						tbl23[k] = sliced20
					end
				end

				if tbl23 then
					set(tbl23)
				end

				return arg
			end

			return arg
		end

		local function slicedfn35(arg, arg2)
			local sliced20 = string.gsub(tostring(arg.Spec.Text or ""), "%d", "0")
			return tostring(slicedn18) .. "|" .. tostring(arg2) .. "|" .. sliced20
		end

		local function slicedfn36(arg, arg2)
			local eggRecords = tbl.EggRecords
			if type(eggRecords) ~= "table" or type(eggRecords.GrowthSecondsRemaining) ~= "function" then
				return 0, 0
			end
			local slicedn25 = 1

			if type(eggRecords.GrowthSpeedMultiplier) == "function" then
				local ok, result = pcall(eggRecords.GrowthSpeedMultiplier, arg)

				if ok and type(result) == "number" then
					slicedn25 = result
				end
			end

			local ok, result = pcall(eggRecords.GrowthSecondsRemaining, arg, arg2, slicedn25)
			ok = ok and type(result) == "number"
			local slicedn26 = 0

			if not ok then
				result = slicedn26
			end

			local slicedn27 = 0

			if type(eggRecords.GrowthDuration) == "function" then
				local ok2
				ok2, slicedn27 = pcall(eggRecords.GrowthDuration, arg)
				ok2 = ok2 and type(slicedn27) == "number"
				local slicedn28 = 0

				if not ok2 then
					slicedn27 = slicedn28
				end
			end

			return result, slicedn27
		end

		local function slicedfn37(arg)
			local eggRecords = tbl.EggRecords

			if type(eggRecords) == "table" and type(eggRecords.WeightKg) == "function" then
				local ok, result = pcall(eggRecords.WeightKg, arg)
				if ok and type(result) == "number" then
					return result
				end
			end

			return 0
		end

		slicedfn8 = function()
			local eggState = tbl.EggState
			if type(eggState) ~= "table" or type(eggState.ReadOwnerEggs) ~= "function" then
				return nil
			end
			local ok, result = pcall(eggState.ReadOwnerEggs, localPlayer.UserId)
			if not ok or type(result) ~= "table" then
				return nil
			end
			local serverTimeNow = workspace:GetServerTimeNow()
			local tbl23 = {}

			for k, sliced20 in pairs(result) do
				if type(sliced20) == "table" then
					local sliced21 = tbl7.AssetInfo(sliced20.AssetCategory)
					local slicedn25 = tonumber(sliced20.AssetScale) or 0
					local mutations = type(sliced20.Mutations) == "table" and sliced20.Mutations or {}

					local tbl24 = {
						Id = k,
						Info = sliced21,
						Scale = slicedn25,
						Weight = slicedfn37(sliced20),
						Mutations = mutations,
						Income = tbl7.Income(sliced21, slicedn25, mutations),
						Status = "Inventory",
						Remaining = math.huge,
						Percent = 0,
					}

					if sliced20.Placement ~= nil then
						local ok2, result2 = pcall(eggState.IsReadyToHatch, k)

						if ok2 and result2 then
							tbl24.Status = "Ready"
							tbl24.Remaining = 0
							tbl24.Percent = 100
						else
							local sliced22, sliced23 = slicedfn36(sliced20, serverTimeNow)
							tbl24.Status = "Growing"
							tbl24.Remaining = sliced22

							if sliced23 > 0 then
								tbl24.Percent = math.clamp(math.floor((1 - sliced22 / sliced23) * 100), 0, 100)
							end
						end
					end

					table.insert(tbl23, tbl24)
				end
			end

			return tbl23
		end

		slicedfn9 = function(arg)
			local sort = tbl10.Sort

			table.sort(arg, function(arg2, arg3)
				if sort == tbl8[2] and arg2.Info.RarityNumber ~= arg3.Info.RarityNumber then
					return arg2.Info.RarityNumber > arg3.Info.RarityNumber
				end

				if sort == tbl8[3] and arg2.Remaining ~= arg3.Remaining then
					return arg2.Remaining < arg3.Remaining
				end
				return arg2.Income > arg3.Income
			end)
		end

		local function slicedfn38(arg)
			if arg.Status == "Ready" then
				return bold(paint(color2.Ready, "Ready to hatch"))
			end

			if arg.Status == "Growing" then
				return bold(paint(color2.Clock, tbl7.FormatClock(arg.Remaining))) .. tbl7.Separator() .. paint(color2.Growing, arg.Percent .. "%")
			end
			return paint(color2.Inventory, "In inventory")
		end

		local function slicedfn39(arg)
			local tbl23 = {}
			local sliced20 = tbl7.MutationText(arg.Mutations)
			table.insert(tbl23, bold(paint(color2.Income, tbl7.FormatRate(arg.Income))))
			table.insert(tbl23, paint(color2.Scale, string.format("%.2fx", arg.Scale)))
			table.insert(tbl23, paint(color2.Weight, tbl7.FormatWeight(arg.Weight)))

			if sliced20 ~= "" then
				table.insert(tbl23, sliced20)
			end

			return table.concat(tbl23, tbl7.Separator())
		end

		local slicedn25 = 5
		local slicedn26 = slicedn25 + 0.8
		local slicedn27 = 1.2
		local slicedn28 = 1.2
		local slicedn29 = 0.936
		local slicedn30 = 2.3
		local slicedn31 = 0.25
		local slicedn32 = 0.18
		local slicedn33 = slicedn30 + 0.6
		local slicedn34 = 0.24
		local slicedn35 = 0.22

		local function slicedfn40(arg)
			if string.upper(tostring(arg.Rarity)) == "SECRET" then
				return tbl7.SecretGradient
			end
			return arg.Gradient
		end

		local function slicedfn41(arg)
			return slicedfn40(arg) ~= nil and Color3.fromRGB(255, 255, 255) or arg.Color
		end

		local function slicedfn42(arg)
			if string.upper(tostring(arg.Rarity)) == "SECRET" then
				return tbl7.SecretRotation
			end
			return nil
		end

		local function slicedfn43(arg)
			local sliced20 = arg and arg.Get()
			if not sliced20 or slicedn18 <= 0 then
				return nil
			end

			if sliced20.Text ~= tostring(arg.Spec.Text or "") then
				return nil
			end
			return sliced20
		end

		local function slicedfn44(arg)
			local sliced20 = slicedfn35(arg, "w")
			if arg.WidthKey == sliced20 then
				return arg.WidthUnits
			end
			local sliced21 = slicedfn43(arg)
			if not sliced21 then
				return nil
			end
			local size = sliced21.Size
			local textWrapped = sliced21.TextWrapped
			sliced21.TextWrapped = false
			sliced21.Size = UDim2.fromOffset(100000, math.max(1, size.Y.Offset))
			local x = sliced21.TextBounds.X
			sliced21.Size = size
			sliced21.TextWrapped = textWrapped
			if x <= 0 then
				return nil
			end
			local widthUnits = x / slicedn18
			arg.WidthKey = sliced20
			arg.WidthUnits = widthUnits
			return arg.WidthUnits
		end

		local function slicedfn45(arg, arg2)
			local sliced20 = slicedfn35(arg, math.floor(arg2 * 100 + 0.5))
			if arg.HeightKey == sliced20 then
				return arg.HeightUnits
			end
			local sliced21 = slicedfn43(arg)
			if not sliced21 then
				return nil
			end
			local size = sliced21.Size
			sliced21.Size = UDim2.fromOffset(math.max(1, math.floor(arg2 * slicedn18 + 0.5)), 100000)
			local y = sliced21.TextBounds.Y
			sliced21.Size = size
			if y <= 0 then
				return nil
			end
			local heightUnits = y / slicedn18
			arg.HeightKey = sliced20
			arg.HeightUnits = heightUnits
			return arg.HeightUnits
		end

		local function slicedfn46(arg)
			local rfEggWorldAskHatch = networking:FindFirstChild("RF/EggWorld/AskHatch")
			if not rfEggWorldAskHatch or not rfEggWorldAskHatch:IsA("RemoteFunction") then
				return false
			end
			local ok, result = pcall(rfEggWorldAskHatch.InvokeServer, rfEggWorldAskHatch, arg)
			if not ok or result == false then
				return false
			end
			task.wait(0.35)
			local rfEggWorldAskFinishHatch = networking:FindFirstChild("RF/EggWorld/AskFinishHatch")

			if rfEggWorldAskFinishHatch and rfEggWorldAskFinishHatch:IsA("RemoteFunction") then
				pcall(rfEggWorldAskFinishHatch.InvokeServer, rfEggWorldAskFinishHatch, arg)
			end

			return true
		end

		tbl22.RunAction = function()
			local focus = tbl22.Focus
			if type(focus) ~= "table" or focus.Id == nil then
				return
			end
			local str = tostring(focus.Id)

			if focus.Status == "Inventory" then
				local eggState = tbl.EggState
				if type(eggState) == "table" and type(eggState.WearEggTool) == "function" and pcall(eggState.WearEggTool, str) then
					return
				end
				local rfEggWorldAskWearTool = networking:FindFirstChild("RF/EggWorld/AskWearTool")

				if rfEggWorldAskWearTool and rfEggWorldAskWearTool:IsA("RemoteFunction") then
					pcall(rfEggWorldAskWearTool.InvokeServer, rfEggWorldAskWearTool, str)
				end

				return
			end

			if focus.Status == "Ready" then
				if not tbl22.Hatching then
					tbl22.Hatching = true
					pcall(slicedfn46, str)
					tbl22.Hatching = false
				end

				return
			end

			if tbl22.Flying or type(tbl4.FlyTo) ~= "function" then
				return
			end
			local placedEggRenders = workspace:FindFirstChild("PlacedEggRenders")
			local sliced20 = nil

			if placedEggRenders then
				for _, child in ipairs(placedEggRenders:GetChildren()) do
					if string.find(child.Name, str, 1, true) or child:GetAttribute("Uid") == str then
						sliced20 = child
						break
					end
				end
			end

			if not sliced20 then
				return
			end

			local ok, result = pcall(function()
				return sliced20:IsA("Model") and sliced20:GetPivot() or sliced20.CFrame
			end)

			if not ok then
				return
			end
			local movement = tbl4.Movement
			if movement.Owner ~= nil and movement.Owner ~= "treadmill" or movement.PlaceWanted or tbl4.Steal.Active or tbl4.Steal.Wanted or tbl4.Steal.Carrying then
				return
			end
			tbl22.Flying = true

			if tbl4.ClaimMovement("predictor") then
				if tbl4.Treadmill.Riding or tbl4.OnBelt() then
					pcall(tbl4.ExitBelt)
				end

				pcall(tbl4.FlyTo, result.Position + Vector3.new(0, 3, 0), function()
					return false
				end, "fly")

				tbl4.ReleaseMovement("predictor")
			end

			tbl22.Flying = false
		end

		slicedfn10 = function(arg)
			sliced9 = arg
			arg:SetDock(5, { Gap = slicedn35, DividerColor = Color3.fromRGB(170, 174, 184) })
			local sliced20 = arg:Dock()

			tbl22.Icon = arg:Image({
				Parent = sliced20,
				X = 0,
				Y = 0,
				Width = slicedn25,
				Height = slicedn25,
				Corner = 0.35,
				Background = "#000000",
				BackgroundTransparency = 0.26,
				StrokeThickness = slicedn16,
				StrokeTransparency = 0,
				ZIndex = 8,
			})

			tbl22.Name = arg:Text({
				Parent = sliced20,
				X = slicedn26,
				Y = 0,
				Height = slicedn27,
				Scale = slicedn28,
				Wrap = false,
				Gradient = tbl7.NameGradient,
				TextStrokeTransparency = 1,
				ZIndex = 9,
			})

			tbl22.Rarity = arg:Text({
				Parent = sliced20,
				X = slicedn26,
				Y = 0,
				Height = slicedn27,
				Scale = slicedn29,
				Wrap = false,
				Font = tbl7.RarityFont,
				TextStrokeTransparency = 1,
				StrokeTransparency = 0.08,
				ZIndex = 9,
			})

			tbl22.Info = arg:Text({ Parent = sliced20, X = slicedn26, Y = slicedn27, Height = slicedn25 - slicedn27, Wrap = false, ZIndex = 9 })

			tbl22.Action = arg:Button({
				Parent = sliced20,
				X = 0,
				Y = 0,
				Width = 5,
				Height = slicedn27 - 0.1,
				Text = "",
				Scale = 1,
				Background = "#000000",
				BackgroundTransparency = 0.55,
				HoverTransparency = 0.3,
				PressTransparency = 0.15,
				Corner = 0.35,
				StrokeColor = Color3.fromRGB(255, 255, 255),
				StrokeThickness = slicedn16,
				StrokeTransparency = 0.6,
				Visible = false,
				ZIndex = 10,
				Callback = function()
					if type(tbl22.RunAction) == "function" then
						task.spawn(tbl22.RunAction)
					end
				end,
			})

			arg:OnResize(function(arg2, arg3, arg4)
				if arg3 == slicedn20 and arg4 == slicedn21 then
					return
				end
				slicedn20 = arg3
				slicedn21 = arg4
				slicedn17 = arg3 / math.max(arg4, 1)
				slicedn18 = arg4
				slicedn2 = 2
				slicedn19 = 0.9 / math.max(arg:TextSize(), 1)
				tbl22.Rarity.Set({ StrokeThickness = slicedn19 })

				for _, sliced21 in ipairs(tbl11) do
					sliced21.Rarity.Set({ StrokeThickness = slicedn19 })
				end
			end)

			for _, sliced21 in ipairs({ "Icon", "Name", "Rarity", "Info", "Action" }) do
				slicedfn34(tbl22[sliced21])
			end
		end

		slicedfn11 = function(arg)
			local sliced20 = tbl12[arg]

			if not sliced20 then
				sliced20 = sliced9:Text({ Name = "Line", X = 0, Y = 0, Width = 1, Height = 1, Wrap = true, Visible = false })
				tbl12[arg] = slicedfn34(sliced20)
			end

			return sliced20
		end

		slicedfn12 = function(arg)
			local sliced20 = tbl11[arg]
			if sliced20 then
				return sliced20
			end
			local tbl23 = {}

			tbl23.Frame = sliced9:Button({
				Name = "Entry",
				Text = "",
				Background = "#000000",
				BackgroundTransparency = 0.74,
				HoverTransparency = 0.46,
				PressTransparency = 0.3,
				Corner = 0.35,
				X = 0,
				Y = 0,
				Width = 1,
				Height = 1,
				Visible = false,
				Callback = function()
					if tbl23.Id ~= nil then
						id = tbl23.Id
						requestEggRefresh()
					end
				end,
			})

			tbl23.Icon = sliced9:Image({
				Parent = tbl23.Frame,
				X = slicedn31,
				Y = 0,
				Width = slicedn30,
				Height = slicedn30,
				Corner = 0.35,
				Background = "#000000",
				BackgroundTransparency = 0.45,
				StrokeThickness = slicedn16,
				StrokeTransparency = 0,
			})

			tbl23.Name = sliced9:Text({
				Parent = tbl23.Frame,
				X = slicedn31 + slicedn33,
				Y = 0,
				Width = 1,
				Height = slicedn27,
				Scale = slicedn28,
				Wrap = false,
				Gradient = tbl7.NameGradient,
				TextStrokeTransparency = 1,
			})

			tbl23.Rarity = sliced9:Text({
				Parent = tbl23.Frame,
				X = slicedn31 + slicedn33,
				Y = 0,
				Width = 1,
				Height = slicedn27,
				Scale = slicedn29,
				Wrap = false,
				Font = tbl7.RarityFont,
				TextStrokeTransparency = 1,
				StrokeTransparency = 0.08,
				StrokeThickness = slicedn19,
			})

			tbl23.Detail = sliced9:Text({
				Parent = tbl23.Frame,
				X = slicedn31 + slicedn33,
				Y = slicedn27,
				Width = math.max(1, slicedn17 - slicedn33 - slicedn31 * 2),
				Height = 1,
				Wrap = true,
			})

			tbl23.Status = sliced9:Text({ Parent = tbl23.Frame, X = 0, Y = 0, Width = 1, Height = slicedn27, Wrap = false, Align = "Right" })

			for _, sliced21 in ipairs({ "Frame", "Icon", "Name", "Rarity", "Detail", "Status" }) do
				slicedfn34(tbl23[sliced21])
			end

			tbl11[arg] = tbl23
			return tbl23
		end

		slicedfn13 = function(arg)
			local tbl23 = { Ready = 0, Growing = 0, Inventory = 0 }
			local slicedn36 = 0
			local sliced20 = nil

			for _, sliced21 in ipairs(arg) do
				local status = sliced21.Status
				tbl23[status] = tbl23[status] + 1
				slicedn36 += sliced21.Income

				if not sliced20 or sliced21.Income > sliced20.Income then
					sliced20 = sliced21
				end
			end

			return bold(paint(color2.Text, tostring(#arg) .. " eggs")) .. tbl7.Separator() .. bold(paint(color2.Ready, tbl23.Ready .. " ready")) .. tbl7.Separator() .. bold(paint(color2.Growing, tbl23.Growing .. " growing")) .. tbl7.Separator() .. bold(paint(color2.Inventory, tbl23.Inventory .. " in bag")) .. tbl7.Separator() .. paint(color2.Text, "Total") .. " " .. bold(paint(color2.Income, tbl7.FormatRate(slicedn36))), sliced20
		end

		slicedfn14 = function(arg, arg2)
			if arg2 == "" then
				return true
			end
			local str = " " .. arg.Status
			local sliced20 = string.lower(tostring(arg.Info.Name) .. " " .. tostring(arg.Info.Rarity) .. str)

			for _, mutation in ipairs(arg.Mutations) do
				sliced20 ..= " " .. string.lower(tostring(mutation))
			end

			return string.find(sliced20, arg2, 1, true) ~= nil
		end

		local function slicedfn47(arg)
			local tbl23 = {}
			local sliced20 = bold(paint(color2.Income, tbl7.FormatRate(arg.Income)))
			local str = paint(color2.Scale, string.format("%.2fx", arg.Scale)) .. tbl7.Separator() .. paint(color2.Weight, tbl7.FormatWeight(arg.Weight))
			tbl23[1] = sliced20
			tbl23[2] = str

			do
				local values = table.pack(slicedfn38(arg))
				table.move(values, 1, values.n, 3, tbl23)
			end

			local sliced21 = tbl7.MutationText(arg.Mutations)
			table.insert(tbl23, sliced21 ~= "" and sliced21 or paint(color2.Hint, "Tap an egg below to preview it"))
			return table.concat(tbl23, "\n")
		end

		slicedfn15 = function(arg)
			local flag11 = tbl10.Spotlight and arg ~= nil

			if sliced19 ~= flag11 then
				sliced19 = flag11
				sliced9:SetDock(flag11 and 5 or 0, { Gap = slicedn35 })
			end

			tbl22.Icon.Set({ Visible = flag11 })
			tbl22.Name.Set({ Visible = flag11 })
			tbl22.Rarity.Set({ Visible = flag11 })
			tbl22.Info.Set({ Visible = flag11 })
			tbl22.Action.Set({ Visible = flag11 })
			tbl22.Focus = flag11 and arg or nil
			if not flag11 then
				return
			end
			local info = arg.Info

			tbl22.Action.Set({
				Text = arg.Status == "Inventory" and bold(paint(color2.Inventory, "Hold egg")) or (arg.Status == "Ready" and bold(paint(color2.Ready, "Hatch egg")) or bold(paint(color2.Growing, "Fly to egg"))),
			})

			tbl22.Icon.Set({ Visible = info.Icon ~= nil, Image = info.Icon or "", StrokeColor = info.Color })
			tbl22.Name.Set({ Text = tbl7.Escape(info.Name) })

			tbl22.Rarity.Set({
				Text = string.upper(tostring(info.Rarity)),
				Color = slicedfn41(info),
				Gradient = slicedfn40(info),
				GradientRotation = slicedfn42(info),
			})

			tbl22.Info.Set({ Text = slicedfn47(arg) })
		end

		slicedfn16 = function(arg, arg2)
			local info = arg2.Info
			arg.Id = arg2.Id
			arg.Frame.Set({ Visible = true, BackgroundTransparency = arg2.Id == id and 0.12 or 0.74 })
			arg.Icon.Set({ Visible = info.Icon ~= nil, Image = info.Icon or "", StrokeColor = info.Color })
			arg.Name.Set({ Text = tbl7.Escape(info.Name) })

			arg.Rarity.Set({
				Text = string.upper(tostring(info.Rarity)),
				Color = slicedfn41(info),
				Gradient = slicedfn40(info),
				GradientRotation = slicedfn42(info),
			})

			arg.Detail.Set({ Text = slicedfn39(arg2) })
			arg.Status.Set({ Text = slicedfn38(arg2) })
		end

		slicedfn17 = function()
			if slicedn17 <= 0 then
				return
			end
			flag = false
			local slicedn36 = math.max(1, slicedn17 - slicedn26)
			local sliced20 = slicedfn44(tbl22.Action)

			if sliced20 then
				tbl22.ActionUnits = sliced20 + 1.4
			else
				flag = true
			end

			local slicedn37 = math.min(tbl22.ActionUnits or 5, slicedn36 * 0.45)
			local slicedn38 = math.max(1, slicedn36 - slicedn37 - slicedn34)
			tbl22.Action.Set({ X = slicedn17 - slicedn37, Y = 0.05, Width = slicedn37, Height = slicedn27 - 0.1 })
			local sliced21 = slicedfn44(tbl22.Rarity)

			if sliced21 then
				slicedn24 = sliced21 + 0.1
			else
				flag = true
			end

			local sliced22 = slicedfn44(tbl22.Name)

			if sliced22 then
				slicedn23 = math.min(sliced22 + 0.1, math.max(1, slicedn38 - slicedn24 - slicedn34))
			else
				flag = true
			end

			tbl22.Name.Set({ X = slicedn26, Y = 0, Width = slicedn23, Height = slicedn27 })

			tbl22.Rarity.Set({
				X = slicedn26 + slicedn23 + slicedn34,
				Y = 0,
				Width = math.max(0.5, math.min(slicedn24, slicedn38 - slicedn23 - slicedn34)),
				Height = slicedn27,
			})

			tbl22.Info.Set({ X = slicedn26, Y = slicedn27, Width = slicedn36, Height = math.max(1, slicedn25 - slicedn27) })
			local slicedn39 = math.max(1, slicedn17 - slicedn33 - slicedn31 * 2)
			local slicedn40 = 0

			for _, sliced23 in ipairs(tbl13) do
				if sliced23.Kind == "text" then
					local handle = sliced23.Handle
					local sliced24 = slicedfn45(handle, slicedn17)

					if sliced24 then
						sliced23.Height = sliced24
					else
						flag = true
					end

					local slicedn41 = math.max(1, sliced23.Height or 1)
					handle.Set({ X = 0, Y = slicedn40 + (sliced23.Gap and 0.5 or 0), Width = slicedn17, Height = slicedn41 })
					slicedn40 += slicedn41 + slicedn35 * 0.5 + (sliced23.Gap and 0.5 or 0)
				else
					local item = sliced23.Item
					local sliced24 = slicedfn45(item.Detail, slicedn39)

					if sliced24 then
						item.DetailUnits = sliced24
					else
						flag = true
					end

					local slicedn41 = math.clamp(item.DetailUnits or 1, 1, 4)
					local sliced25 = slicedfn44(item.Status)

					if sliced25 then
						item.StatusUnits = sliced25 + 0.23
					else
						flag = true
					end

					local slicedn42 = math.min(slicedn39 * 0.42, math.max(2.73, item.StatusUnits or 2.73))
					local slicedn43 = math.max(1, slicedn39 - slicedn42 - slicedn34)
					local sliced26 = slicedfn44(item.Rarity)

					if sliced26 then
						item.RarityUnits = sliced26 + 0.1
					else
						flag = true
					end

					local slicedn44 = math.min(item.RarityUnits or 3, slicedn43 * 0.5)
					local sliced27 = slicedfn44(item.Name)

					if sliced27 then
						item.NameUnits = sliced27 + 0.1
					else
						flag = true
					end

					local min = math.min
					local max = math.max
					local nameUnits = item.NameUnits or 4
					local max2 = math.max
					local slicedn45 = slicedn43 - slicedn44 - slicedn34
					local sliced28 = min(max(1, nameUnits), max2(1, slicedn45))
					local slicedn46 = slicedn32 * 2
					local slicedn47 = math.max(slicedn41 + slicedn27, 2.3) + slicedn46
					local slicedn48 = (slicedn47 - slicedn41 - slicedn27) / 2
					item.Frame.Set({ X = 0, Y = slicedn40, Width = slicedn17, Height = slicedn47 })
					item.Icon.Set({ Y = (slicedn47 - slicedn30) / 2 })
					item.Name.Set({ X = slicedn31 + slicedn33, Y = slicedn48, Width = sliced28 })
					item.Rarity.Set({ X = slicedn31 + slicedn33 + sliced28 + slicedn34, Y = slicedn48, Width = math.max(0.5, slicedn44) })
					item.Detail.Set({ X = slicedn31 + slicedn33, Y = slicedn48 + slicedn27, Width = slicedn39, Height = slicedn41 })

					item.Status.Set({
						Visible = sliced23.HasStatus,
						X = slicedn31 + slicedn33 + slicedn39 - slicedn42,
						Y = slicedn48,
						Width = math.max(0.5, slicedn42),
					})

					slicedn40 += slicedn47 + slicedn35
				end
			end

			local slicedn41 = math.max(1, slicedn40)

			if math.abs(slicedn41 - slicedn22) > 0.01 then
				slicedn22 = slicedn41
				sliced9:SetContentLines(slicedn41)
			end
		end
	end
end

local slicedfn18, TweenService, GuiService, StarterGui, antiGuard, tbl14, SourcesAntiGuard

do
	local function slicedfn19()
		if not sliced9 then
			return
		end
		slicedn2 = 2
		local sliced10 = slicedfn8()
		table.clear(tbl13)
		local slicedn4 = 0

		local function slicedfn20(arg, arg2)
			slicedn4 += 1
			local sliced11 = slicedfn11(slicedn4)
			sliced11.Set({ Visible = true, Text = arg })
			table.insert(tbl13, { Kind = "text", Handle = sliced11, Gap = arg2 })
		end

		local slicedn5

		if not sliced10 then
			slicedfn15(nil)
			slicedfn20(bold(paint(color2.Hint, "Egg data is not available yet")), false)
			slicedn5 = 0
		else
			slicedfn9(sliced10)
			local sliced11, sliced12 = slicedfn13(sliced10)
			slicedfn20(sliced11, false)
			local sliced13 = nil

			if id ~= nil then
				sliced13 = nil

				for _, sliced14 in ipairs(sliced10) do
					if sliced14.Id == id then
						sliced13 = sliced14
						break
					else
						sliced13 = nil
					end
				end
			end

			slicedfn15(sliced13 or sliced12)
			local sliced14 = string.lower(sliced9:Query())
			local tbl15 = {}

			for _, sliced15 in ipairs(sliced10) do
				if slicedfn14(sliced15, sliced14) then
					table.insert(tbl15, sliced15)
				end
			end

			if #tbl15 == 0 then
				slicedfn20(paint(color2.Hint, #sliced10 == 0 and "No eggs yet" or string.format("No results for \"%s\"", tbl7.Escape(sliced14))), false)
				slicedn5 = 0
			else
				slicedn5 = 0

				for _, sliced15 in ipairs(tbl9) do
					local tbl16 = {}

					for _, sliced16 in ipairs(tbl15) do
						if sliced16.Status == sliced15.Key then
							table.insert(tbl16, sliced16)
						end
					end

					if #tbl16 > 0 then
						local flag4 = #tbl13 > 0
						slicedfn20(string.format("<b><font color=\"%s\">%s</font></b> <font color=\"#AAAAAA\">(%d)</font>", sliced15.Color, sliced15.Title, #tbl16), flag4)

						for _, sliced16 in ipairs(tbl16) do
							slicedn5 += 1
							local sliced17 = slicedfn12(slicedn5)
							slicedfn16(sliced17, sliced16)
							table.insert(tbl13, { Kind = "item", Item = sliced17, HasStatus = true })
						end
					end
				end
			end
		end

		for i = slicedn4 + 1, #tbl12 do
			tbl12[i].Set({ Visible = false })
		end

		for i = slicedn5 + 1, #tbl11 do
			tbl11[i].Frame.Set({ Visible = false })
		end

		slicedfn17()
		slicedn2 = 2
	end

	tbl7.RequestEggRefresh = requestEggRefresh

	if not tbl7.Ready then
		sliced7:CreateText({ Name = "Egg Predictor", Text = "Update the SourcesHub library to use the predictor canvas." })
	else
		sliced7:CreateDropdown({
			Name = "Sort By",
			Options = tbl8,
			Default = tbl8[1],
			Callback = function(sort)
				if table.find(tbl8, sort) then
					tbl10.Sort = sort
					requestEggRefresh()
				end
			end,
		})

		sliced7:CreateToggle({
			Name = "Preview Card",
			Default = true,
			Callback = function(arg)
				tbl10.Spotlight = arg == true
				requestEggRefresh()
			end,
		})

		local sliced10 = sliced7:CreateCanvas({
			Name = "Egg Predictor",
			Search = true,
			SearchPlaceholder = "Search eggs...",
			Layout = "free",
			Style = {
				TextScale = 0.84,
				LineHeight = 1.1,
				MinLines = 16,
				MaxLines = 32,
				BackgroundTransparency = 0.5,
				ScrollBarColor = Color3.fromRGB(170, 174, 184),
				TextColor = Color3.fromRGB(255, 255, 255),
				TextStrokeTransparency = 0.7,
			},
			Build = function(arg)
				slicedfn10(arg)
				requestEggRefresh()
			end,
		})

		slicedfn4(function()
			sliced10:Destroy()
		end)

		local connection = RunService.Heartbeat:Connect(function(deltaTime)
			local sliced11 = tbl7.PageVisible()
			local flag4

			if sliced11 then
				flag4 = sliced9 == nil or tbl7.IsShown(sliced9:Root())
			else
				flag4 = sliced11
			end

			if flag4 and not flag3 then
				flag2 = true
			end

			flag3 = flag4
			if not sliced11 then
				return
			end
			slicedn3 += deltaTime

			if flag4 and flag2 or slicedn3 >= n then
				slicedn3 = 0

				if flag4 then
					flag2 = false
					pcall(slicedfn19)
				end

				if tbl7.RefreshFuse then
					pcall(tbl7.RefreshFuse)
				end
			end

			if flag4 and (slicedn2 > 0 or flag) then
				if slicedn2 > 0 then
					slicedn2 -= 1
				end

				pcall(slicedfn17)
			end

			if tbl7.PlaceFuse then
				tbl7.PlaceFuse()
			end
		end)

		slicedfn4(function()
			connection:Disconnect()
		end)
	end

	local paint2, bold2, color3, slicedn4, slicedn5, slicedn6, slicedn7, slicedn8, slicedn9, slicedn10
	local slicedn11, slicedn12, slicedn13, sliced10

	do
		local tbl15 = {
			{ min = 0.85, max = 1.05, weight = 2000 },
			{ min = 1.45, max = 1.55, weight = 250 },
			{ min = 1.9, max = 2.1, weight = 125 },
			{ min = 2.85, max = 3.15, weight = 62.5 },
			{ min = 3.8, max = 4.2, weight = 31.25 },
			{ min = 0.3, max = 0.45, weight = 18 },
			{ min = 0.1, max = 0.2, weight = 5 },
			{ min = 5.8, max = 6.2, weight = 15.625 },
			{ min = 9.5, max = 12.5, weight = 3 },
			{ min = 12, max = 17, weight = 0.05 },
			{ min = 20, max = 35, weight = 0.0001 },
		}

		paint2 = tbl7.Paint
		bold2 = tbl7.Bold
		color3 = tbl7.Color
		slicedn4 = 5
		slicedn5 = slicedn4 + 0.8
		slicedn6 = 1.2
		slicedn7 = 1.2
		slicedn8 = 0.936
		slicedn9 = 2.3
		slicedn10 = 0.25
		slicedn11 = 0.18
		slicedn12 = slicedn9 + 0.6
		local slicedn14 = 0.24
		slicedn13 = 0.22
		local slicedn15 = 0.0909
		sliced10 = nil
		local tbl16 = {}
		local tbl17 = {}
		local tbl18 = {}
		local tbl19 = {}
		local slicedn16 = 0
		local slicedn17 = 0
		local slicedn18 = 0.06
		local slicedn19 = -1
		local slicedn20 = -1
		local slicedn21 = -1
		local slicedn22 = 4
		local slicedn23 = 3
		local flag4 = false
		local slicedn24 = 0
		local sliced11 = nil

		local tbl20 = {
			{ Min = 0, Color = "#8F98A8" },
			{ Min = 0.3, Color = "#C6CDDA" },
			{ Min = 0.85, Color = "#FFFFFF" },
			{ Min = 1.45, Color = "#7CFF9E" },
			{ Min = 1.9, Color = "#4FE0FF" },
			{ Min = 2.85, Color = "#6FA0FF" },
			{ Min = 3.8, Color = "#C08BFF" },
			{ Min = 5.8, Color = "#FF9A3D" },
			{ Min = 9.5, Color = "#FF5C5C" },
			{ Min = 12, Color = "#FFD34D" },
			{ Min = 20, Color = "#FF4DE8" },
		}

		local function slicedfn20(arg)
			local slicedn25 = -math.huge
			local str = "#FFFFFF"

			for _, sliced12 in ipairs(tbl20) do
				if arg + 0.001 >= sliced12.Min and sliced12.Min > slicedn25 then
					str = sliced12.Color
					slicedn25 = sliced12.Min
				end
			end

			return str
		end

		local function slicedfn21(arg, arg2)
			local eggRecords = tbl.EggRecords
			if type(eggRecords) ~= "table" or type(eggRecords.WeightKgForScale) ~= "function" then
				return nil
			end
			local ok, result = pcall(eggRecords.WeightKgForScale, arg, arg2)
			if ok and type(result) == "number" and result > 0 then
				return result
			end
			return nil
		end

		local function slicedfn22(arg)
			if type(arg) ~= "table" or #arg == 0 then
				return nil
			end
			local slicedn25 = -math.huge
			local sliced12 = nil

			for _, sliced13 in ipairs(arg) do
				local sliced14 = tbl7.MutationMultiplier({ sliced13 })

				if sliced14 > slicedn25 then
					slicedn25 = sliced14
					sliced12 = sliced13
				end
			end

			return sliced12
		end

		local function slicedfn23()
			if sliced11 then
				return sliced11
			end
			local eggRecords = tbl.EggRecords
			local getupvalues_ = type(debug) == "table" and debug.getupvalues or getupvalues

			if type(eggRecords) == "table" and type(eggRecords.DrawAssetScale) == "function" and type(getupvalues_) == "function" then
				local ok, result = pcall(getupvalues_, eggRecords.DrawAssetScale)

				if ok and type(result) == "table" then
					for _, sliced12 in pairs(result) do
						if type(sliced12) == "table" and type(sliced12[1]) == "table" and sliced12[1].min and sliced12[1].weight then
							sliced11 = sliced12
							break
						end
					end
				end
			end

			sliced11 = sliced11 or tbl15
			return sliced11
		end

		local function slicedfn24(arg, arg2, arg3)
			local fuseKernel = tbl.FuseKernel

			if type(fuseKernel) == "table" and type(fuseKernel.BandWeightBias) == "function" then
				local ok, result = pcall(fuseKernel.BandWeightBias, arg, arg2, arg3)
				if ok and type(result) == "number" then
					return result
				end
			end

			return math.exp(math.log((arg[1] + arg[2] + arg[3]) / 3) / 0.69314718055994529 * (math.log((arg2 + arg3) / 2) / 0.69314718055994529) * 0.6)
		end

		local function slicedfn25()
			local save = tbl.Save
			if type(save) ~= "table" or type(save.Get) ~= "function" then
				return nil
			end
			local ok, result = pcall(save.Get)
			if not ok or type(result) ~= "table" then
				return nil
			end
			local fusionSlots = type(result.FusionSlots) == "table" and result.FusionSlots or {}
			local inventory = type(result.Inventory) == "table" and result.Inventory or {}
			local tbl21 = {}

			for i = 1, 3 do
				local sliced12 = fusionSlots[i]
				local flag5 = sliced12 ~= nil and inventory[sliced12] or nil

				if type(flag5) == "table" then
					table.insert(tbl21, {
						Category = flag5.Category,
						Scale = tonumber(flag5.Scale) or 1,
						Mutations = type(flag5.Mutations) == "table" and flag5.Mutations or {},
					})
				end
			end

			return {
				Items = tbl21,
				Locked = result.FusionLocked == true,
				Duration = tonumber(result.FusionDuration) or 0,
				Reward = result.FusionEggReward ~= nil and result.FusionEggReward ~= false,
			}
		end

		local function slicedfn26(arg)
			if string.upper(tostring(arg.Rarity)) == "SECRET" then
				return tbl7.SecretGradient
			end
			return arg.Gradient
		end

		local function slicedfn27(arg)
			return slicedfn26(arg) ~= nil and Color3.fromRGB(255, 255, 255) or arg.Color
		end

		local function slicedfn28(arg)
			if string.upper(tostring(arg.Rarity)) == "SECRET" then
				return tbl7.SecretRotation
			end
			return nil
		end

		local function slicedfn29(arg)
			sliced10 = arg
			arg:SetDock(5, { Gap = slicedn13, DividerColor = Color3.fromRGB(170, 174, 184) })
			local sliced12 = arg:Dock()

			tbl16.Icon = arg:Image({
				Parent = sliced12,
				X = 0,
				Y = 0,
				Width = slicedn4,
				Height = slicedn4,
				Corner = 0.35,
				Background = "#000000",
				BackgroundTransparency = 0.26,
				StrokeThickness = slicedn15,
				StrokeTransparency = 0,
				ZIndex = 8,
			})

			tbl16.Name = arg:Text({
				Parent = sliced12,
				X = slicedn5,
				Y = 0,
				Height = slicedn6,
				Scale = slicedn7,
				Wrap = false,
				Gradient = tbl7.NameGradient,
				TextStrokeTransparency = 1,
				ZIndex = 9,
			})

			tbl16.Rarity = arg:Text({
				Parent = sliced12,
				X = slicedn5,
				Y = 0,
				Height = slicedn6,
				Scale = slicedn8,
				Wrap = false,
				Font = tbl7.RarityFont,
				TextStrokeTransparency = 1,
				StrokeTransparency = 0.08,
				ZIndex = 9,
			})

			tbl16.Info = arg:Text({ Parent = sliced12, X = slicedn5, Y = slicedn6, Height = slicedn4 - slicedn6, Wrap = false, ZIndex = 9 })

			arg:OnResize(function(arg2, arg3, arg4)
				if arg3 == slicedn19 and arg4 == slicedn20 then
					return
				end
				slicedn19 = arg3
				slicedn20 = arg4
				slicedn16 = arg3 / math.max(arg4, 1)
				slicedn17 = arg4
				slicedn24 = 2
				slicedn18 = 0.9 / math.max(arg:TextSize(), 1)
				tbl16.Rarity.Set({ StrokeThickness = slicedn18 })

				for _, sliced13 in ipairs(tbl17) do
					sliced13.Rarity.Set({ StrokeThickness = slicedn18 })
				end
			end)
		end

		local function slicedfn30(arg)
			local sliced12 = arg and arg.Get()
			if not sliced12 or slicedn17 <= 0 then
				return nil
			end

			if sliced12.Text ~= tostring(arg.Spec.Text or "") then
				return nil
			end
			return sliced12
		end

		local function slicedfn31(arg)
			local sliced12 = slicedfn30(arg)
			if not sliced12 then
				return nil
			end
			local size = sliced12.Size
			local textWrapped = sliced12.TextWrapped
			sliced12.TextWrapped = false
			sliced12.Size = UDim2.fromOffset(100000, math.max(1, size.Y.Offset))
			local x = sliced12.TextBounds.X
			sliced12.Size = size
			sliced12.TextWrapped = textWrapped
			if x <= 0 then
				return nil
			end
			return x / slicedn17
		end

		local function slicedfn32(arg, arg2)
			local sliced12 = slicedfn30(arg)
			if not sliced12 then
				return nil
			end
			local size = sliced12.Size
			sliced12.Size = UDim2.fromOffset(math.max(1, math.floor(arg2 * slicedn17 + 0.5)), 100000)
			local y = sliced12.TextBounds.Y
			sliced12.Size = size
			if y <= 0 then
				return nil
			end
			return y / slicedn17
		end

		local function slicedfn33(arg)
			local sliced12 = tbl18[arg]

			if not sliced12 then
				local sliced13 = sliced10:Text({ Name = "Line", X = 0, Y = 0, Width = 1, Height = 1, Wrap = true, Visible = false })
				tbl18[arg] = sliced13
				sliced12 = sliced13
			end

			return sliced12
		end

		local function slicedfn34(arg)
			local sliced12 = tbl17[arg]
			if sliced12 then
				return sliced12
			end

			local tbl21 = {
				Frame = sliced10:Frame({
					Name = "Slot",
					Background = "#000000",
					BackgroundTransparency = 0.74,
					Corner = 0.35,
					X = 0,
					Y = 0,
					Width = 1,
					Height = 1,
					Visible = false,
				}),
			}

			tbl21.Icon = sliced10:Image({
				Parent = tbl21.Frame,
				X = slicedn10,
				Y = 0,
				Width = slicedn9,
				Height = slicedn9,
				Corner = 0.35,
				Background = "#000000",
				BackgroundTransparency = 0.45,
				StrokeThickness = slicedn15,
				StrokeTransparency = 0,
			})

			tbl21.Name = sliced10:Text({
				Parent = tbl21.Frame,
				X = slicedn10 + slicedn12,
				Y = 0,
				Width = 1,
				Height = slicedn6,
				Scale = slicedn7,
				Wrap = false,
				Gradient = tbl7.NameGradient,
				TextStrokeTransparency = 1,
			})

			tbl21.Rarity = sliced10:Text({
				Parent = tbl21.Frame,
				X = slicedn10 + slicedn12,
				Y = 0,
				Width = 1,
				Height = slicedn6,
				Scale = slicedn8,
				Wrap = false,
				Font = tbl7.RarityFont,
				TextStrokeTransparency = 1,
				StrokeTransparency = 0.08,
				StrokeThickness = slicedn18,
			})

			tbl21.Detail = sliced10:Text({
				Parent = tbl21.Frame,
				X = slicedn10 + slicedn12,
				Y = slicedn6,
				Width = math.max(1, slicedn16 - slicedn12 - slicedn10 * 2),
				Height = 1,
				Wrap = true,
			})

			tbl21.Status = sliced10:Text({
				Parent = tbl21.Frame,
				X = 0,
				Y = 0,
				Width = 1,
				Height = slicedn6,
				Wrap = false,
				Align = "Right",
				Color = color3.Hint,
			})

			tbl17[arg] = tbl21
			return tbl21
		end

		local function slicedfn35()
			if slicedn16 <= 0 then
				return
			end
			flag4 = false
			local slicedn25 = math.max(1, slicedn16 - slicedn5)
			local sliced12 = slicedfn31(tbl16.Rarity)

			if sliced12 then
				slicedn23 = sliced12 + 0.1
			else
				flag4 = true
			end

			local sliced13 = slicedfn31(tbl16.Name)

			if sliced13 then
				slicedn22 = math.min(sliced13 + 0.1, math.max(1, slicedn25 - slicedn23 - slicedn14))
			else
				flag4 = true
			end

			tbl16.Name.Set({ X = slicedn5, Y = 0, Width = slicedn22, Height = slicedn6 })

			tbl16.Rarity.Set({
				X = slicedn5 + slicedn22 + slicedn14,
				Y = 0,
				Width = math.max(0.5, math.min(slicedn23, slicedn25 - slicedn22 - slicedn14)),
				Height = slicedn6,
			})

			tbl16.Info.Set({ X = slicedn5, Y = slicedn6, Width = slicedn25, Height = math.max(1, slicedn4 - slicedn6) })
			local slicedn26 = math.max(1, slicedn16 - slicedn12 - slicedn10 * 2)
			local slicedn27 = 0

			for _, sliced14 in ipairs(tbl19) do
				if sliced14.Kind == "text" then
					local handle = sliced14.Handle
					local sliced15 = slicedfn32(handle, slicedn16)

					if sliced15 then
						sliced14.Height = sliced15
					else
						flag4 = true
					end

					local slicedn28 = math.max(1, sliced14.Height or 1)
					handle.Set({ X = 0, Y = slicedn27 + (sliced14.Gap and 0.5 or 0), Width = slicedn16, Height = slicedn28 })
					slicedn27 += slicedn28 + slicedn13 * 0.5 + (sliced14.Gap and 0.5 or 0)
				else
					local slot = sliced14.Slot
					local sliced15 = slicedfn32(slot.Detail, slicedn26)

					if sliced15 then
						slot.DetailUnits = sliced15
					else
						flag4 = true
					end

					local slicedn28 = math.clamp(slot.DetailUnits or 1, 1, 4)
					local sliced16 = slicedfn31(slot.Status)

					if sliced16 then
						slot.StatusUnits = sliced16 + 0.23
					else
						flag4 = true
					end

					local slicedn29 = math.min(slicedn26 * 0.42, math.max(2.73, slot.StatusUnits or 2.73))
					local slicedn30 = math.max(1, slicedn26 - slicedn29 - slicedn14)
					local sliced17 = slicedfn31(slot.Rarity)

					if sliced17 then
						slot.RarityUnits = sliced17 + 0.1
					else
						flag4 = true
					end

					local slicedn31 = math.min(slot.RarityUnits or 3, slicedn30 * 0.5)
					local sliced18 = slicedfn31(slot.Name)

					if sliced18 then
						slot.NameUnits = sliced18 + 0.1
					else
						flag4 = true
					end

					local min = math.min
					local max = math.max
					local nameUnits = slot.NameUnits or 4
					local max2 = math.max
					local slicedn32 = slicedn30 - slicedn31 - slicedn14
					local sliced19 = min(max(1, nameUnits), max2(1, slicedn32))
					local slicedn33 = slicedn11 * 2
					local slicedn34 = math.max(slicedn28 + slicedn6, 2.3) + slicedn33
					local slicedn35 = (slicedn34 - slicedn28 - slicedn6) / 2
					slot.Frame.Set({ X = 0, Y = slicedn27, Width = slicedn16, Height = slicedn34 })
					slot.Icon.Set({ Y = (slicedn34 - slicedn9) / 2 })
					slot.Name.Set({ X = slicedn10 + slicedn12, Y = slicedn35, Width = sliced19 })
					slot.Rarity.Set({ X = slicedn10 + slicedn12 + sliced19 + slicedn14, Y = slicedn35, Width = math.max(0.5, slicedn31) })
					slot.Detail.Set({ X = slicedn10 + slicedn12, Y = slicedn35 + slicedn6, Width = slicedn26, Height = slicedn28 })
					slot.Status.Set({ X = slicedn10 + slicedn12 + slicedn26 - slicedn29, Y = slicedn35, Width = math.max(0.5, slicedn29) })
					slicedn27 += slicedn34 + slicedn13
				end
			end

			local slicedn28 = math.max(1, slicedn27)

			if math.abs(slicedn28 - slicedn21) > 0.01 then
				slicedn21 = slicedn28
				sliced10:SetContentLines(slicedn28)
			end
		end

		local function slicedfn36(arg, arg2)
			local flag5 = arg ~= nil
			sliced10:SetDock(flag5 and 5 or 0, { Gap = slicedn13 })
			tbl16.Icon.Set({ Visible = flag5 })
			tbl16.Name.Set({ Visible = flag5 })
			tbl16.Rarity.Set({ Visible = flag5 })
			tbl16.Info.Set({ Visible = flag5 })
			if not flag5 then
				return
			end
			tbl16.Icon.Set({ Visible = arg.Icon ~= nil, Image = arg.Icon or "", StrokeColor = arg.Color })
			tbl16.Name.Set({ Text = tbl7.Escape(arg.Name) })

			tbl16.Rarity.Set({
				Text = string.upper(tostring(arg.Rarity)),
				Color = slicedfn27(arg),
				Gradient = slicedfn26(arg),
				GradientRotation = slicedfn28(arg),
			})

			local sliced12 = paint2(color3.Text, string.format("Fusing %d of 3 pets", #arg2.Items))

			if arg2.Reward then
				sliced12 = bold2(paint2(color3.Ready, "Fuse finished, claim your egg"))
			elseif arg2.Locked then
				local slicedn25 = arg2.Duration > 1e9 and arg2.Duration - workspace:GetServerTimeNow() or 0
				sliced12 = bold2(paint2(color3.Clock, slicedn25 > 0 and "Fusing" .. tbl7.Separator() .. tbl7.FormatClock(slicedn25) or "Fusing"))
			end

			local set = tbl16.Info.Set
			local tbl21 = {}
			local concat = table.concat
			local tbl22 = {}
			local sliced13 = bold2(paint2(color3.Income, tbl7.FormatRate(tbl7.Income(arg, arg2.Items[1].Scale, arg2.Items[1].Mutations))))
			local sliced14 = paint2(color3.Text, string.format("%d/3 loaded", #arg2.Items))
			tbl22[1] = sliced13
			tbl22[2] = sliced14
			tbl22[3] = sliced12
			tbl21.Text = concat(tbl22, "\n")
			set(tbl21)
		end

		local function refreshFuse()
			if not sliced10 then
				return
			end
			slicedn24 = 2
			table.clear(tbl19)
			local slicedn25 = 0

			local function slicedfn37(arg, arg2)
				slicedn25 += 1
				local sliced12 = slicedfn33(slicedn25)
				sliced12.Set({ Visible = true, Text = arg })
				table.insert(tbl19, { Kind = "text", Handle = sliced12, Gap = arg2 })
			end

			local function slicedfn38(arg, arg2)
				local flag5 = #tbl19 > 0
				slicedfn37(string.format("<b><font color=\"%s\">%s</font></b>", arg2, arg), flag5)
			end

			local sliced12 = slicedfn25()
			local slicedn26

			if not sliced12 then
				slicedfn36(nil, nil)
				slicedfn37(bold2(paint2(color3.Hint, "Fuse machine data is not available yet")), false)
				slicedn26 = 0
			elseif #sliced12.Items == 0 then
				slicedfn36(nil, nil)
				slicedfn37(bold2(paint2(color3.Text, "Machine is empty")), false)
				slicedfn37(paint2(color3.Hint, "Load 3 pets of the same species to see the result odds"), false)
				slicedn26 = 0
			else
				local items = sliced12.Items
				local sliced13 = tbl7.AssetInfo(items[1].Category)
				slicedfn36(sliced13, sliced12)
				local text = color3.Text
				slicedfn38(string.format("FUSE MACHINE STATUS (%d/3 PETS)", #items), text)
				slicedfn37(paint2(color3.Hint, "Species") .. "  " .. bold2(paint2(sliced13.Hex, "[" .. string.upper(tostring(sliced13.Rarity)) .. "]")) .. " " .. bold2(paint2(color3.Text, tbl7.Escape(sliced13.Name))), false)
				slicedn26 = 0

				for i = 1, 3 do
					local sliced14 = items[i]
					slicedn26 += 1
					local sliced15 = slicedfn34(slicedn26)
					sliced15.Frame.Set({ Visible = true })
					sliced15.Status.Set({ Text = "SLOT " .. i })

					if sliced14 then
						sliced15.Icon.Set({ Visible = sliced13.Icon ~= nil, Image = sliced13.Icon or "", StrokeColor = sliced13.Color })
						sliced15.Name.Set({ Text = tbl7.Escape(sliced13.Name) })

						sliced15.Rarity.Set({
							Text = string.upper(tostring(sliced13.Rarity)),
							Color = slicedfn27(sliced13),
							Gradient = slicedfn26(sliced13),
							GradientRotation = slicedfn28(sliced13),
						})

						local sliced16 = slicedfn21(sliced14.Category, sliced14.Scale)
						local sliced17 = bold2(paint2(color3.Scale, string.format("%.2fx", sliced14.Scale)))

						if sliced16 then
							sliced17 ..= tbl7.Separator() .. paint2(color3.Weight, tbl7.FormatWeight(sliced16))
						end

						local str = sliced17 .. tbl7.Separator() .. bold2(paint2(color3.Income, tbl7.FormatRate(tbl7.Income(sliced13, sliced14.Scale, sliced14.Mutations))))
						local sliced18 = tbl7.MutationText(sliced14.Mutations)

						sliced15.Detail.Set({
							Text = str .. tbl7.Separator() .. (sliced18 ~= "" and sliced18 or paint2(color3.Hint, "Normal")),
						})
					else
						sliced15.Icon.Set({ Visible = false })
						sliced15.Name.Set({ Text = paint2(color3.Hint, "Empty") })
						sliced15.Rarity.Set({ Text = "", Gradient = nil })
						sliced15.Detail.Set({ Text = paint2(color3.Hint, "Add a pet to this slot") })
					end

					table.insert(tbl19, { Kind = "slot", Slot = sliced15 })
				end

				local slicedn27 = 0

				for _, item in ipairs(items) do
					slicedn27 += item.Scale
				end

				local slicedn28 = slicedn27 / #items
				local sliced14 = slicedfn21(items[1].Category, slicedn28)
				local str = paint2(color3.Hint, "Average Scale") .. "  " .. bold2(paint2(color3.Scale, string.format("%.2fx", slicedn28)))

				if sliced14 then
					str ..= tbl7.Separator() .. paint2(color3.Weight, tbl7.FormatWeight(sliced14))
				end

				slicedfn37(str, false)
				local sliced15 = nil

				for _, item in ipairs(items) do
					local sliced16 = slicedfn22(item.Mutations)

					if sliced16 then
						if (sliced15 and tbl7.MutationMultiplier({ sliced15 }) or 0) < tbl7.MutationMultiplier({ sliced16 }) then
							sliced15 = sliced16
						end
					end
				end

				local tbl21 = sliced15 and { sliced15 } or {}
				slicedfn38("PREDICTED SIZE PROBABILITIES", color3.Income)

				if #items == 3 then
					local tbl22 = { items[1].Scale, items[2].Scale, items[3].Scale }
					local tbl23 = {}
					local slicedn29 = 0

					for _, sliced16 in ipairs(slicedfn23()) do
						local slicedn30 = sliced16.weight * slicedfn24(tbl22, sliced16.min, sliced16.max)
						slicedn29 += slicedn30
						table.insert(tbl23, { Min = sliced16.min, Max = sliced16.max, Weight = slicedn30, Color = slicedfn20(sliced16.min) })
					end

					table.sort(tbl23, function(arg, arg2)
						return arg.Weight > arg2.Weight
					end)

					local sliced16 = tbl23[1]

					for _, sliced17 in ipairs(tbl23) do
						local slicedn30 = slicedn29 > 0 and sliced17.Weight / slicedn29 * 100 or 0
						local sliced18 = bold2(paint2(sliced17.Color, string.format("%.2fx - %.2fx", sliced17.Min, sliced17.Max)))
						local sliced19 = slicedfn21(items[1].Category, sliced17.Min)
						local sliced20 = slicedfn21(items[1].Category, sliced17.Max)

						if sliced19 and sliced20 then
							local weight = color3.Weight
							local format = string.format
							local formatWeight = tbl7.FormatWeight
							sliced18 ..= tbl7.Separator() .. paint2(weight, format("%s - %s", tbl7.FormatWeight(sliced19), formatWeight(sliced20)))
						end

						slicedfn37(sliced18 .. tbl7.Separator() .. bold2(paint2(slicedn30 >= 10 and color3.Income or (slicedn30 >= 1 and color3.Clock or color3.Hint), string.format(slicedn30 >= 1 and "%.1f%%" or "%.3f%%", slicedn30))), false)
					end

					slicedfn38("RESULT PREDICTION", color3.Text)
					slicedfn37(paint2(color3.Hint, "Predicted Mutation") .. "  " .. (sliced15 and tbl7.MutationText(tbl21) or paint2(color3.Text, "Normal")), false)

					if sliced16 then
						slicedfn37(paint2(color3.Hint, "Estimated Value") .. "  " .. bold2(paint2(color3.Income, tbl7.FormatRate(tbl7.Income(sliced13, sliced16.Min, tbl21)) .. " ~ " .. tbl7.FormatRate(tbl7.Income(sliced13, sliced16.Max, tbl21)))) .. tbl7.Separator() .. paint2(color3.Hint, "at ") .. bold2(paint2(sliced16.Color, string.format("%.2fx - %.2fx", sliced16.Min, sliced16.Max))), false)
					end

					local sliced17, sliced18, sliced19 = ipairs(tbl23)
					local sliced20 = nil

					for _, sliced21 in sliced17, sliced18, sliced19 do
						if not sliced20 or sliced21.Max > sliced20.Max then
							sliced20 = sliced21
						end
					end

					if sliced20 then
						slicedfn37(paint2(color3.Hint, "Best Case") .. "  " .. bold2(paint2(sliced20.Color, string.format("%.2fx - %.2fx", sliced20.Min, sliced20.Max))) .. "  " .. bold2(paint2(color3.Income, tbl7.FormatRate(tbl7.Income(sliced13, sliced20.Max, tbl21)))), false)
					end
				else
					slicedfn37(paint2(color3.Hint, string.format("Load %d more of the same species to see the odds", 3 - #sliced12.Items)), false)
				end
			end

			for i = slicedn25 + 1, #tbl18 do
				tbl18[i].Set({ Visible = false })
			end

			for i = slicedn26 + 1, #tbl17 do
				tbl17[i].Frame.Set({ Visible = false })
			end

			slicedfn35()
			slicedn24 = 2
		end

		if not tbl7.Ready then
			sliced8:CreateText({
				Name = "Fuse Predictor",
				Text = "Update the SourcesHub library to use the predictor canvas.",
			})
		else
			local sliced12 = sliced8:CreateCanvas({
				Name = "Fuse Predictor",
				Layout = "free",
				Style = {
					TextScale = 0.84,
					LineHeight = 1.1,
					MinLines = 16,
					MaxLines = 34,
					BackgroundTransparency = 0.5,
					ScrollBarColor = Color3.fromRGB(170, 174, 184),
					TextColor = Color3.fromRGB(255, 255, 255),
					TextStrokeTransparency = 0.7,
				},
				Build = function(arg)
					slicedfn29(arg)

					if type(tbl7.RequestEggRefresh) == "function" then
						tbl7.RequestEggRefresh()
					end
				end,
			})

			tbl7.RefreshFuse = refreshFuse

			tbl7.PlaceFuse = function()
				if slicedn24 > 0 or flag4 then
					if slicedn24 > 0 then
						slicedn24 -= 1
					end

					pcall(slicedfn35)
				end
			end

			slicedfn4(function()
				sliced12:Destroy()
			end)
		end
	end

	local sliced11 = sliced2:CreateTab({ Name = "Progress", SectionsExpanded = true }):CreateSection({ Name = "Auto Progression", Expanded = true })

	do
		local tbl15 = {}
		local tbl16

		tbl16 = {
			Remote = function(arg)
				local sliced12 = tbl15[arg]
				if sliced12 ~= nil then
					return sliced12 or nil
				end
				local sliced13 = networking:FindFirstChild(arg)
				tbl15[arg] = sliced13 or false
				return sliced13
			end,
			Invoke = function(arg, ...)
				local sliced12 = tbl16.Remote(arg)
				if not sliced12 or not sliced12:IsA("RemoteFunction") then
					return false, nil
				end
				local ok, result = pcall(sliced12.InvokeServer, sliced12, ...)
				return ok, result
			end,
			Fire = function(arg, ...)
				local sliced12 = tbl16.Remote(arg)
				if not sliced12 or not sliced12:IsA("RemoteEvent") then
					return false
				end
				return pcall(sliced12.FireServer, sliced12, ...)
			end,
		}

		local function saveData()
			local save = tbl.Save
			if type(save) ~= "table" or type(save.Get) ~= "function" then
				return nil
			end
			local ok, result = pcall(save.Get)
			return ok and type(result) == "table" and result or nil
		end

		tbl16.SaveData = saveData
		local tbl17 = { "Money", "Cash", "Coins", "Currency", "Balance" }

		tbl16.Money = function()
			local sliced12 = saveData()

			if sliced12 then
				for _, sliced13 in ipairs(tbl17) do
					local num = tonumber(sliced12[sliced13])
					if num then
						return num
					end
				end
			end

			local leaderstats = localPlayer:FindFirstChild("leaderstats")

			if leaderstats then
				for _, sliced13 in ipairs(tbl17) do
					local sliced14 = leaderstats:FindFirstChild(sliced13)
					if sliced14 and tonumber(sliced14.Value) then
						return tonumber(sliced14.Value)
					end
				end
			end

			return nil
		end

		tbl16.AddWorker = tbl3.Add
		tbl16.Backoff = tbl3.Backoff

		local tbl18 = {
			"Money",
			"BaseUpgradeLevel",
			"TreadmillUpgradeLevel",
			"TrailInventory",
			"PendingOfflineMoney",
		}

		local save = tbl.Save

		if type(save) == "table" and type(save.FieldSignal) == "function" then
			for _, sliced12 in ipairs(tbl18) do
				local ok, result = pcall(save.FieldSignal, sliced12)

				if ok and type(result) == "table" and type(result.Connect) == "function" then
					local ok2, result2 = pcall(result.Connect, result, function()
						tbl3.Wake()
					end)

					if ok2 and result2 then
						slicedfn4(function()
							pcall(function()
								result2:Disconnect()
							end)
						end)
					end
				end
			end
		end

		local sliced12 = nil
		local sliced13 = nil
		local tbl19 = {}

		local function slicedfn20()
			local sliced14 = slicedfn2(function()
				return ReplicatedStorage.Data.Trails
			end)

			local directory = type(sliced14) == "table" and sliced14.Directory or nil
			if type(directory) ~= "table" then
				return {}
			end
			local tbl20 = {}

			for k, sliced15 in pairs(directory) do
				if type(sliced15) == "table" then
					table.insert(tbl20, { Id = tostring(sliced15._id or k), Price = tonumber(sliced15.Price) or math.huge })
				end
			end

			table.sort(tbl20, function(arg, arg2)
				return arg.Price < arg2.Price
			end)

			return tbl20
		end

		local function slicedfn21(arg)
			if not tbl6.ReadToggle(sliced12, false) then
				return false
			end
			sliced13 = sliced13 or slicedfn20()
			local sliced14 = tbl16.SaveData()
			if not sliced14 or #sliced13 == 0 then
				return false
			end
			local trailInventory = type(sliced14.TrailInventory) == "table" and sliced14.TrailInventory or {}
			local slicedn14 = tonumber(sliced14.Money) or 0

			for _, sliced15 in ipairs(sliced13) do
				if trailInventory[sliced15.Id] ~= true and not tbl19[sliced15.Id] and sliced15.Price <= slicedn14 then
					local AskPurchase, sliced16 = tbl16.Invoke("RF/Trailwear/AskPurchase", sliced15.Id)
					if AskPurchase and sliced16 ~= false then
						return true
					end
					tbl19[sliced15.Id] = true
					tbl16.Backoff(arg)
					return false
				end
			end

			return false
		end

		sliced12 = sliced11:CreateToggle({
			Name = "Auto Buy Trail",
			Note = "Automatically buy available trails when affordable",
			Default = false,
			Callback = function()
				table.clear(tbl19)
				sliced13 = nil
			end,
		})

		tbl16.AddWorker(slicedfn21)
		local sliced14 = nil

		local function slicedfn22()
			if not tbl6.ReadToggle(sliced14, false) then
				return false
			end
			local sliced15 = tbl16.SaveData()
			if not sliced15 then
				return false
			end

			local sliced16 = slicedfn2(function()
				return ReplicatedStorage.Data.Bases
			end)

			local bases = type(sliced16) == "table" and sliced16.BASES or nil
			if type(bases) ~= "table" then
				return false
			end
			local slicedn14 = tonumber(sliced15.BaseUpgradeLevel) or 0
			local ok = nil

			if type(sliced16.GetMaxBaseLevel) == "function" then
				local result
				ok, result = pcall(sliced16.GetMaxBaseLevel)
				ok = ok and tonumber(result) or nil
			end

			if ok and slicedn14 >= ok then
				return false
			end
			local sliced17 = bases[slicedn14 + 1]
			local num = type(sliced17) == "table" and tonumber(sliced17.Cost) or nil

			if num then
				num = (tonumber(sliced15.Money) or 0) >= num
			end

			if num then
				return tbl16.Fire("RE/Homestead/AskBaseTierRaise")
			end
			return false
		end

		sliced14 = sliced11:CreateToggle({
			Name = "Auto Upgrade Base",
			Note = "Automatically upgrade base when money is available",
			Default = false,
		})

		tbl16.AddWorker(slicedfn22)
		local sliced15 = nil

		local function slicedfn23()
			if not tbl6.ReadToggle(sliced15, false) then
				return false
			end
			local sliced16 = tbl16.SaveData()
			if not sliced16 then
				return false
			end

			local sliced17 = slicedfn2(function()
				return ReplicatedStorage.Data.Treadmills
			end)

			if type(sliced17) ~= "table" or type(sliced17.GetByUpgradeLevel) ~= "function" then
				return false
			end
			local ok, result = pcall(sliced17.GetByUpgradeLevel, (tonumber(sliced16.TreadmillUpgradeLevel) or 0) + 1)
			if not ok or type(result) ~= "table" then
				return false
			end
			local id2 = result._id
			local huge = tonumber(result.Price) or math.huge
			local flag4 = type(id2) == "string"

			if flag4 then
				flag4 = (tonumber(sliced16.Money) or 0) >= huge
			end

			if flag4 then
				local AskTierRaise, sliced18 = tbl16.Invoke("RF/Treadmill/AskTierRaise", id2)
				return AskTierRaise and sliced18 ~= false
			end
			return false
		end

		sliced15 = sliced11:CreateToggle({
			Name = "Auto Upgrade Treadmill",
			Note = "Automatically upgrade treadmill when money is available",
			Default = false,
		})

		tbl16.AddWorker(slicedfn23)
		local slicedn14 = 15
		local sliced16 = nil
		local slicedn15 = 15
		local now = os.clock()

		local function slicedfn24()
			if not tbl6.ReadToggle(sliced16, false) then
				return false
			end
			local now2 = os.clock()
			slicedn15 += now2 - now
			now = now2
			local num = tbl16.SaveData()
			num = num and tonumber(num.PendingOfflineMoney) or nil

			if num == nil then
				local PendingCheck, sliced17 = tbl16.Invoke("RF/AwayEarnings/PendingCheck")
				num = PendingCheck and sliced17 ~= false and sliced17 ~= nil and 1 or 0
			end

			local flag4 = false

			if num > 0 then
				local sliced17
				flag4, sliced17 = tbl16.Invoke("RF/AwayEarnings/AskCollect")
				flag4 = flag4 and sliced17 ~= false
			end

			if slicedn14 <= slicedn15 then
				slicedn15 = 0
				local AskRedeemAll, sliced17 = tbl16.Invoke("RF/Codex/AskRedeemAll")
				flag4 = flag4 or AskRedeemAll and sliced17 ~= false
				tbl16.Invoke("RF/Codex/AskRedeemLimitedEgg")
			end

			return flag4
		end

		sliced16 = sliced11:CreateToggle({
			Name = "Auto Claim",
			Note = "Claim offline money & index rewards",
			Default = false,
			Callback = function()
				slicedn15 = slicedn14
			end,
		})

		tbl16.AddWorker(slicedfn24)
	end

	tbl4.IndexClaimHandle = sliced11:CreateToggle({
		Name = "Auto Claim Index",
		Note = "Claim index rewards as soon as they unlock",
		Default = false,
		Callback = function()
			if type(tbl4.IndexClaimRestart) == "function" then
				tbl4.IndexClaimRestart()
			end
		end,
	})

	slicedfn18 = function(arg, arg2)
		if type(v.Notify) == "function" then
			pcall(v.Notify, arg, arg2, 5)
		end
	end

	local sliced12 = sliced2:CreateTab({ Name = "Server", SectionsExpanded = true }):CreateSection({ Name = "Server", Expanded = true })
	local TeleportService = game:GetService("TeleportService")
	local HttpService = game:GetService("HttpService")
	local GuiService2 = game:GetService("GuiService")

	do
		local function slicedfn20()
			if false then
				return queue_on_teleport
			end

			if type(queueonteleport) == "function" then
				return queueonteleport
			end

			if type(syn) == "table" and type(syn.queue_on_teleport) == "function" then
				return syn.queue_on_teleport
			end

			if type(fluxus) == "table" and type(fluxus.queue_on_teleport) == "function" then
				return fluxus.queue_on_teleport
			end
			return nil
		end

		local function slicedfn21(arg)
			pcall(function()
				TeleportService:SetTeleportSetting("__SourcesAutoLoadScriptEnabled", arg)
			end)

			if not arg then
				return true
			end
			local sliced13 = slicedfn20()
			if not sliced13 then
				return false
			end

			return true
		end

		local sliced13 = nil

		local function slicedfn22()
			if sliced13 and tbl4.Toggle(sliced13, false) then
				slicedfn21(true)
			end
		end

		sliced13 = nil

		local str = "Least Players"
		local slicedn14 = 10
		local slicedn15 = 0
		local sliced14 = nil
		local tbl15 = {}
		local flag4 = false
		local slicedn16 = 0
		local flag5 = false
		local sliced15 = nil
		local str2 = ""
		local slicedn17 = 0
		local slicedn18 = 60

		local function slicedfn23(arg)
			slicedn15 = 0
			sliced14 = nil

			if arg then
				tbl15[arg] = true
			end
		end

		pcall(function()
			TeleportService.TeleportInitFailed:Connect(function(arg, arg2, arg3)
				if not sliced14 then
					return
				end
				slicedfn23(sliced14)
				flag5 = true

				if not flag4 then
					slicedfn18("Server Hop Failed", tostring(arg3 ~= "" and arg3 or arg2))
				end
			end)
		end)

		local function slicedfn24(arg)
			local str3 = tostring(game.JobId or "")
			local tbl16 = {}
			local flag6 = arg == "Random"
			local str4 = arg == "Least Players" and "Asc" or "Desc"
			local slicedn19 = flag6 and 3 or 6
			local nextPageCursor = nil

			for i = 1, slicedn19 do
				local str5 = string.format("https://games.roblox.com/v1/games/%d/servers/Public?sortOrder=%s&excludeFullGames=true&limit=100", game.PlaceId, str4)

				if nextPageCursor and nextPageCursor ~= "" then
					str5 ..= "&cursor=" .. HttpService:UrlEncode(nextPageCursor)
				end

				local ok, result = pcall(function()
					return HttpService:JSONDecode(game:HttpGet(str5))
				end)

				if not ok or type(result) ~= "table" then
					return tbl16, false
				end
				local ipairs = ipairs
				local data = result.data or {}

				for _, sliced17 in ipairs(data) do
					local str6 = tostring(sliced17.id or "")
					local huge = tonumber(sliced17.playing) or math.huge
					local slicedn20 = tonumber(sliced17.maxPlayers) or 0

					if str6 ~= "" and str6 ~= str3 and huge < slicedn20 then
						tbl16[#tbl16 + 1] = { Id = str6, Playing = huge, Room = slicedn20 - huge }
					end
				end

				if #tbl16 > 0 and not flag6 then
					break
				end
				nextPageCursor = result.nextPageCursor
				if not nextPageCursor or nextPageCursor == "" then
					break
				end
			end

			return tbl16, true
		end

		local function serverHop(arg)
			local sliced16

			if sliced15 and str2 == arg and os.clock() - slicedn17 < slicedn18 then
				sliced16 = sliced15
			else
				local sliced17
				sliced16, sliced17 = slicedfn24(arg)
				if not sliced17 then
					return "fetch"
				end
				sliced15 = sliced16
				str2 = arg
				slicedn17 = os.clock()
			end

			local function slicedfn25(arg2)
				local tbl16 = {}

				for _, sliced17 in ipairs(sliced16) do
					if not tbl15[sliced17.Id] and sliced17.Room >= arg2 then
						tbl16[#tbl16 + 1] = sliced17
					end
				end

				return tbl16
			end

			local sliced17 = slicedfn25(2)

			if #sliced17 == 0 then
				sliced17 = slicedfn25(1)
			end

			if #sliced17 == 0 and next(tbl15) ~= nil then
				table.clear(tbl15)
				sliced17 = slicedfn25(1)
			end

			if #sliced17 == 0 then
				slicedfn23(nil)
				sliced15 = nil
				return "empty"
			end

			local id2

			if arg == "Random" then
				id2 = sliced17[math.random(1, #sliced17)].Id
			else
				table.sort(sliced17, function(arg2, arg3)
					if arg == "Least Players" then
						return arg2.Playing < arg3.Playing
					end
					return arg2.Playing > arg3.Playing
				end)

				id2 = sliced17[1].Id
			end

			flag5 = false
			sliced14 = id2
			slicedn15 = os.clock() + slicedn14
			pcall(slicedfn22)

			if not pcall(function()
				TeleportService:TeleportToPlaceInstance(game.PlaceId, id2, localPlayer)
			end) then
				slicedfn23(id2)
				return "failed"
			end

			local slicedn19 = os.clock() + slicedn14

			while os.clock() < slicedn19 do
				if flag5 then
					return "denied"
				end
				task.wait(0.25)
			end

			return "waiting"
		end

		tbl4.ServerHop = serverHop

		sliced12:CreateDropdown({
			Name = "Server Hop Mode",
			Options = { "Most Players", "Random", "Least Players" },
			Default = "Least Players",
			Callback = function(arg)
				str = tostring(arg or "Least Players")
			end,
		})

		sliced12:CreateButton({
			Name = "Server Hop",
			ButtonText = "Hop",
			Callback = function()
				slicedn16 += 1
				local sliced16 = slicedn16

				task.spawn(function()
					flag4 = true
					local slicedn19 = 0

					while sliced16 == slicedn16 do
						slicedn19 += 1
						local sliced17 = serverHop(str)

						if not (sliced17 == "waiting" or sliced16 ~= slicedn16) then
							if sliced17 == "empty" then
								sliced15 = nil
								table.clear(tbl15)
							end

							if slicedn19 % 10 == 0 then
								slicedfn18("Server Hop", string.format("Every server was full so far, %d tries.", slicedn19))
							end

							task.wait(sliced17 == "fetch" and 1 or 0.1)
							continue
						end

						break
					end

					if sliced16 == slicedn16 then
						flag4 = false
					end
				end)
			end,
		})
	end

	do
		local slicedn14 = 8
		local slicedn15 = 0
		local str = ""
		local sliced13 = nil

		local function slicedfn20()
			return os.clock() < slicedn15
		end

		local function slicedfn21(arg)
			slicedn15 = arg and os.clock() + slicedn14 or 0
		end

		local function slicedfn22(arg)
			local match = tostring(arg or ""):match("^%s*(.-)%s*$")
			return match:match("%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x") or match
		end

		local function slicedfn23()
			local sliced14 = str
			local result = str

			if sliced13 then
				local ok

				ok, result = pcall(function()
					local controller = sliced13._controller
					return controller and controller.GetValue and controller.GetValue()
				end)

				if not (ok and type(result) == "string" and result ~= "") then
					local exitTo = nil

					for _, sliced15 in ipairs({ "Get", "GetValue", "GetText" }) do
						local ok2, result2 = pcall(function()
							return sliced13[sliced15]
						end)

						if ok2 and type(result2) == "function" then
							local ok3
							ok3, result = pcall(result2, sliced13)
							if ok3 and type(result) == "string" and result ~= "" then
								exitTo = 1
								break
							end
						end
					end

					if exitTo ~= 1 then
						result = sliced14
					end
				end
			end

			local sliced15 = slicedfn22(result)

			if sliced15 == "" then
				local ok, result2 = pcall(function()
					local sliced16 = getclipboard or readclipboard or getrbxclipboard
					return type(sliced16) == "function" and sliced16() or nil
				end)

				if ok and type(result2) == "string" then
					sliced15 = slicedfn22(result2)
				end
			end

			return sliced15
		end

		local function slicedfn24(arg)
			if not sliced13 then
				return
			end

			pcall(function()
				local controller = sliced13._controller

				if controller and controller.SetValue then
					controller.SetValue(arg, false)
				end
			end)

			str = slicedfn22(arg)
		end

		local function slicedfn25(arg)
			slicedfn21(true)
			pcall(AutoLoadBeforeTeleport)

			if not pcall(function()
				if game.JobId ~= "" then
					TeleportService:TeleportToPlaceInstance(game.PlaceId, game.JobId, localPlayer)
				else
					TeleportService:Teleport(game.PlaceId, localPlayer)
				end
			end) then
				slicedfn21(false)
				slicedfn18(arg, "Roblox could not rejoin the server.")
			end
		end

		pcall(function()
			TeleportService.TeleportInitFailed:Connect(function(arg, arg2, arg3)
				if not slicedfn20() then
					return
				end
				slicedfn21(false)
				slicedfn18("Teleport Failed", tostring(arg3 ~= "" and arg3 or arg2))
			end)
		end)

		sliced13 = sliced12:CreateInput({
			Name = "Job ID",
			Placeholder = "Paste a server Job ID...",
			Default = "",
			MaxLength = 100,
			Callback = function(arg)
				str = slicedfn22(arg)
			end,
		})

		if sliced13 then
			sliced13._configIgnored = true

			if sliced13.State and not sliced13.State._registered then
				sliced13.State._configIgnored = true
			end
		end

		sliced12:CreateButton({
			Name = "Join Job ID",
			ButtonText = "Join",
			Callback = function()
				if slicedfn20() then
					slicedfn18("Join Job ID Failed", "A teleport is already running, try again shortly.")
					return
				end
				local sliced14 = slicedfn23()
				if sliced14 == "" then
					slicedfn18("Join Job ID Failed", "Paste a valid Job ID first.")
					return
				end
				slicedfn21(true)
				pcall(AutoLoadBeforeTeleport)

				if not pcall(function()
					TeleportService:TeleportToPlaceInstance(game.PlaceId, sliced14, localPlayer)
				end) then
					slicedfn21(false)
					slicedfn18("Join Job ID Failed", "Roblox could not join that server.")
				end
			end,
		})

		sliced12:CreateButton({
			Name = "Copy Current Job ID",
			ButtonText = "Copy",
			Callback = function()
				local str2 = tostring(game.JobId or "")
				slicedfn24(str2)
				local sliced14 = setclipboard or toclipboard
				slicedfn18((type(sliced14) == "function" and pcall(sliced14, str2) or false) and "Job ID Copied" or "Job ID Shown", str2)
			end,
		})

		sliced12:CreateButton({
			Name = "Rejoin Server",
			ButtonText = "Rejoin",
			Callback = function()
				if slicedfn20() then
					slicedfn18("Rejoin Failed", "A teleport is already running, try again shortly.")
					return
				end
				slicedfn25("Rejoin Failed")
			end,
		})

		local tbl15 = { Option = nil, Fired = false, TeleportingAt = 0 }

		local function slicedfn26()
			local robloxPromptGui = CoreGui:FindFirstChild("RobloxPromptGui")
			robloxPromptGui = robloxPromptGui and robloxPromptGui:FindFirstChild("promptOverlay")
			return robloxPromptGui ~= nil and robloxPromptGui:FindFirstChild("ErrorPrompt") ~= nil
		end

		pcall(function()
			local connection = localPlayer.OnTeleport:Connect(function(arg)
				if arg == Enum.TeleportState.Failed then
					tbl15.TeleportingAt = 0
				else
					tbl15.TeleportingAt = os.clock()
				end
			end)

			slicedfn4(function()
				pcall(function()
					connection:Disconnect()
				end)
			end)
		end)

		tbl15.Option = sliced12:CreateToggle({ Name = "Auto Rejoin When Disconnect", Default = true })

		local function slicedfn27(arg)
			if tbl15.Fired or tbl15.Option == nil or not tbl4.Toggle(tbl15.Option, false) or slicedfn20() then
				return
			end
			local flag4 = tbl15.TeleportingAt > 0

			if flag4 then
				local teleportingAt = tbl15.TeleportingAt
				flag4 = os.clock() - teleportingAt < 60
			end

			if flag4 then
				return
			end
			local sliced14 = string.lower(tostring(arg or ""))
			if sliced14 == "" or string.find(sliced14, "teleport", 1, true) then
				return
			end
			local errorCode = nil

			pcall(function()
				errorCode = GuiService2:GetErrorCode()
			end)

			if errorCode == Enum.ConnectionError.DisconnectDuplicatePlayer or string.find(sliced14, "banned", 1, true) or string.find(sliced14, "same account", 1, true) then
				return
			end
			tbl15.Fired = true
			local placeId = game.PlaceId
			local str2 = tostring(game.JobId or "")
			local flag5 = string.find(sliced14, "shut", 1, true) ~= nil or string.find(sliced14, "no longer", 1, true) ~= nil or string.find(sliced14, "closed", 1, true) ~= nil
			pcall(AutoLoadBeforeTeleport)
			slicedfn18("Auto Rejoin", flag5 and "Server closed, joining another one." or "Disconnected, rejoining now.")

			task.spawn(function()
				local slicedn16 = 0

				while true do
					slicedn16 += 1
					local flag6 = not flag5 and str2 ~= "" and slicedn16 <= 2

					pcall(function()
						if flag6 then
							TeleportService:TeleportToPlaceInstance(placeId, str2, localPlayer)
						else
							TeleportService:Teleport(placeId, localPlayer)
						end
					end)

					task.wait(flag6 and 4 or 5)
				end
			end)
		end

		pcall(function()
			local connection = GuiService2.ErrorMessageChanged:Connect(function(arg)
				task.wait(0.3)

				if slicedfn26() then
					slicedfn27(arg)
				end
			end)

			slicedfn4(function()
				pcall(function()
					connection:Disconnect()
				end)
			end)
		end)

		task.spawn(function()
			local robloxPromptGui = CoreGui:WaitForChild("RobloxPromptGui", 30)
			robloxPromptGui = robloxPromptGui and robloxPromptGui:WaitForChild("promptOverlay", 30)
			if not robloxPromptGui then
				return
			end

			local connection = robloxPromptGui.ChildAdded:Connect(function(child)
				if child.Name ~= "ErrorPrompt" then
					return
				end
				task.wait(0.2)
				local str2 = ""

				for _, descendant in ipairs(child:GetDescendants()) do
					if descendant:IsA("TextLabel") and descendant.Name == "ErrorMessage" then
						str2 = descendant.Text
					end
				end

				if str2 == "" then
					pcall(function()
						str2 = GuiService2:GetErrorMessage()
					end)
				end

				slicedfn27(str2 ~= "" and str2 or "disconnected")
			end)

			slicedfn4(function()
				pcall(function()
					connection:Disconnect()
				end)
			end)
		end)
	end

	local sliced13 = sliced2:CreateTab({ Name = "Misc", SectionsExpanded = true })
	local sliced14 = sliced13:CreateSection({ Name = "Performance", Expanded = true })
	local flag4 = false

	local animToggle
	animToggle = sliced14:CreateToggle({
		Name = "UI Optimizer",
		Note = "Removes every interface animation and effect (strokes, gradients, glows, pop-ups)",
		Default = false,
		Callback = function(arg)
			if type(arg) ~= "boolean" then
				arg = tbl4.Toggle(animToggle, true)
			end
			SourcesLib.SetNoAnim(arg == true)
		end,
	})

	local soundToggle
	soundToggle = sliced14:CreateToggle({
		Name = "Interface Sounds",
		Note = "Soft click and open/close sounds",
		Default = true,
		Callback = function(arg)
			if type(arg) ~= "boolean" then
				arg = tbl4.Toggle(soundToggle, true)
			end
			SourcesLib.SoundOn = arg == true
		end,
	})

	

	

	
	do
		local Lighting = game:GetService("Lighting")
		local slicedn14 = 0.003
		local flag5 = false
		local slicedn15 = 0
		local thread = nil
		local tbl15 = {}
		local tbl16 = {}
		local obj = setmetatable({}, { __mode = "k" })
		local tbl17 = {}
		local connection = nil

		local function slicedfn20(arg, arg2, arg3)
			local ok, result = pcall(arg)
			if not ok then
				return
			end
			tbl16[#tbl16 + 1] = { Setter = arg2, Value = result }
			pcall(arg2, arg3)
		end

		local function slicedfn21(arg, arg2, arg3)
			local tbl18 = obj[arg]

			if not tbl18 then
				tbl18 = {}
				obj[arg] = tbl18
			end

			if tbl18[arg2] == nil then
				local ok, result = pcall(function()
					return arg[arg2]
				end)

				if not ok then
					return
				end
				tbl18[arg2] = { Value = result }
			end

			pcall(function()
				arg[arg2] = arg3
			end)
		end

		local function slicedfn22(arg)
			if not flag5 or not arg.Parent then
				return
			end

			if arg:IsA("ParticleEmitter") then
				slicedfn21(arg, "Enabled", false)
				slicedfn21(arg, "Rate", 0)
			elseif arg:IsA("Trail") or arg:IsA("Beam") then
				slicedfn21(arg, "Enabled", false)
			elseif arg:IsA("PointLight") or arg:IsA("SpotLight") or arg:IsA("SurfaceLight") then
				slicedfn21(arg, "Enabled", false)
				slicedfn21(arg, "Brightness", 0)
			elseif arg:IsA("Fire") or arg:IsA("Smoke") or arg:IsA("Sparkles") then
				slicedfn21(arg, "Enabled", false)
			elseif arg:IsA("Explosion") then
				slicedfn21(arg, "Visible", false)
			elseif arg:IsA("SpecialMesh") then
				slicedfn21(arg, "TextureId", "")
			elseif arg:IsA("Decal") or arg:IsA("Texture") then
				if not (arg.Name == "face" and arg.Parent and arg.Parent.Name == "Head") then
					slicedfn21(arg, "Transparency", 1)
				end
			elseif arg:IsA("MeshPart") then
				slicedfn21(arg, "RenderFidelity", Enum.RenderFidelity.Performance)
				slicedfn21(arg, "TextureID", "")
				slicedfn21(arg, "CastShadow", false)
				slicedfn21(arg, "Reflectance", 0)
				slicedfn21(arg, "Material", Enum.Material.SmoothPlastic)
			elseif arg:IsA("BasePart") then
				slicedfn21(arg, "CastShadow", false)
				slicedfn21(arg, "Reflectance", 0)
				slicedfn21(arg, "Material", Enum.Material.SmoothPlastic)
			elseif arg:IsA("PostEffect") then
				slicedfn21(arg, "Enabled", false)
			elseif arg:IsA("Clouds") then
				slicedfn21(arg, "Cover", 0)
				slicedfn21(arg, "Density", 0)
			elseif arg:IsA("Atmosphere") then
				slicedfn21(arg, "Density", 0)
				slicedfn21(arg, "Haze", 0)
				slicedfn21(arg, "Glare", 0)
			end
		end

		local function slicedfn23()
			for _, sliced15 in ipairs(tbl15) do
				if sliced15.Connected then
					sliced15:Disconnect()
				end
			end

			table.clear(tbl15)

			if connection then
				pcall(function()
					connection:Disconnect()
				end)

				connection = nil
			end
		end

		local function slicedfn24()
			local rendering = settings().Rendering
			local terrain = workspace.Terrain

			local function slicedfn25(arg, arg2, arg3)
				slicedfn20(function()
					return arg[arg2]
				end, function(arg4)
					arg[arg2] = arg4
				end, arg3)
			end

			slicedfn25(rendering, "QualityLevel", Enum.QualityLevel.Level01)
			slicedfn25(rendering, "MeshPartDetailLevel", Enum.MeshPartDetailLevel.Level01)
			slicedfn25(rendering, "EditQualityLevel", Enum.QualityLevel.Level01)

			local ok, result = pcall(function()
				return UserSettings():GetService("UserGameSettings")
			end)

			if ok and result then
				slicedfn25(result, "SavedQualityLevel", Enum.SavedQualitySetting.QualityLevel1)
			end

			slicedfn25(Lighting, "GlobalShadows", false)
			slicedfn25(Lighting, "ShadowSoftness", 0)
			slicedfn25(Lighting, "FogEnd", 9e9)
			slicedfn25(Lighting, "Technology", Enum.Technology.Legacy)
			slicedfn25(Lighting, "EnvironmentDiffuseScale", 0)
			slicedfn25(Lighting, "EnvironmentSpecularScale", 0)
			slicedfn25(terrain, "Decoration", false)
			slicedfn25(terrain, "WaterWaveSize", 0)
			slicedfn25(terrain, "WaterWaveSpeed", 0)
			slicedfn25(terrain, "WaterReflectance", 0)
			slicedfn25(terrain, "WaterTransparency", 1)
		end

		local function slicedfn25(arg, arg2)
			local now = os.clock()

			for _, descendant in ipairs(arg:GetDescendants()) do
				if not flag5 or slicedn15 ~= arg2 then
					return false
				end
				slicedfn22(descendant)

				if os.clock() - now > slicedn14 then
					RunService.Heartbeat:Wait()
					now = os.clock()
				end
			end

			return true
		end

		local function slicedfn26()
			if not flag5 or #tbl17 == 0 then
				return
			end
			local now = os.clock()

			while #tbl17 > 0 do
				local sliced15 = table.remove(tbl17)
				slicedfn22(sliced15)
				if not (os.clock() - now > slicedn14) then
					continue
				end
				break
			end
		end

		local function slicedfn27()
			local now = os.clock()

			for k, sliced15 in pairs(obj) do
				if k.Parent then
					for k2, sliced16 in pairs(sliced15) do
						pcall(function()
							k[k2] = sliced16.Value
						end)
					end
				end

				obj[k] = nil

				if slicedn14 < os.clock() - now then
					RunService.Heartbeat:Wait()
					now = os.clock()
				end
			end
		end

		local function slicedfn28()
			if not flag5 then
				return
			end
			flag5 = false
			slicedn15 += 1
			slicedfn23()
			table.clear(tbl17)

			if thread then
				pcall(task.cancel, thread)
				thread = nil
			end

			slicedfn27()

			for i = #tbl16, 1, -1 do
				local sliced15 = tbl16[i]
				pcall(sliced15.Setter, sliced15.Value)
			end

			table.clear(tbl16)
		end

		local function slicedfn29()
			if flag5 then
				return
			end
			flag5 = true
			slicedn15 += 1
			local sliced15 = slicedn15
			slicedfn24()

			local function slicedfn30(arg)
				tbl15[#tbl15 + 1] = arg.DescendantAdded:Connect(function(descendant)
					if flag5 and slicedn15 == sliced15 then
						tbl17[#tbl17 + 1] = descendant
					end
				end)
			end

			slicedfn30(workspace)
			slicedfn30(Lighting)

			connection = RunService.Heartbeat:Connect(function()
				if flag5 and slicedn15 == sliced15 then
					slicedfn26()
				end
			end)

			thread = task.spawn(function()
				if slicedfn25(workspace, sliced15) then
					slicedfn25(Lighting, sliced15)
				end
			end)
		end

		slicedfn4(slicedfn28)

		sliced14:CreateToggle({
			Name = "Optimizer",
			Note = "Strip shadows, textures and effects for the highest FPS",
			Default = false,
			Callback = function(arg)
				if arg then
					slicedfn29()
				else
					task.spawn(slicedfn28)
				end
			end,
		})
	end

	do
		local Stats = game:GetService("Stats")
		local slicedn14 = 132
		local slicedn15 = 0.085
		local slicedn16 = 0.2
		local slicedn17 = 8
		local sliced15 = sliced2:CreateState({ Name = "FPS and Ping Position", Default = {} })

		local function slicedfn20()
			local sliced16 = sliced15:Get()
			if type(sliced16) == "table" and type(sliced16.XOffset) == "number" and type(sliced16.YOffset) == "number" then
				return UDim2.new(tonumber(sliced16.XScale) or 0, sliced16.XOffset, tonumber(sliced16.YScale) or 0, sliced16.YOffset)
			end
			return UDim2.new(0, 16, 0, 16)
		end

		local function slicedfn21(arg)
			sliced15:Set({ XScale = arg.X.Scale, XOffset = arg.X.Offset, YScale = arg.Y.Scale, YOffset = arg.Y.Offset })
		end

		local color4 = Color3.fromRGB(58, 255, 55)
		local color5 = Color3.fromRGB(255, 214, 84)
		local color6 = Color3.fromRGB(255, 96, 96)
		local color7 = Color3.fromRGB(150, 150, 158)
		local flag5 = false
		local tbl15 = {}
		local screenGui = nil
		local frame = nil
		local uiScale = nil
		local sliced16 = nil
		local sliced17 = nil
		local slicedn18 = 1
		local slicedn19 = 0
		local slicedn20 = 0
		local sliced18 = nil
		local sliced19 = nil
		local font = nil

		pcall(function()
			font = Font.new("rbxasset://fonts/families/GothamSSm.json", Enum.FontWeight.ExtraBold, Enum.FontStyle.Normal)
		end)

		local function slicedfn22(arg)
			if arg >= 100 then
				return color4
			end

			if arg >= 50 then
				return color5
			end
			return color6
		end

		local function slicedfn23(arg)
			if arg <= 90 then
				return color4
			end

			if arg <= 180 then
				return color5
			end
			return color6
		end

		local function slicedfn24()
			if not uiScale then
				return
			end
			local currentCamera = workspace.CurrentCamera
			local viewportSize = currentCamera and currentCamera.ViewportSize or Vector2.new(1280, 720)

			if viewportSize.X < 1 then
				viewportSize = Vector2.new(1280, 720)
			end

			uiScale.Scale = math.clamp(viewportSize.X * slicedn15 / slicedn14, 0.7, 1.4) * slicedn18
		end

		local function slicedfn25()
			for _, sliced20 in ipairs(tbl15) do
				pcall(function()
					sliced20:Disconnect()
				end)
			end

			table.clear(tbl15)

			if screenGui then
				pcall(function()
					screenGui:Destroy()
				end)
			end

			screenGui = nil
			frame = nil
			uiScale = nil
			sliced16 = nil
			sliced17 = nil
			sliced18 = nil
			sliced19 = nil
			slicedn19 = 0
		end

		local function createTextLabel(parent, arg, arg2, textColor3)
			local textLabel = Instance.new("TextLabel")
			textLabel.Name = slicedfn3()
			textLabel.BackgroundTransparency = 1
			textLabel.Position = UDim2.fromOffset(arg, 9)
			textLabel.Size = UDim2.fromOffset(arg2, 16)
			textLabel.Text = ""
			textLabel.TextColor3 = textColor3
			textLabel.TextScaled = true
			textLabel.TextXAlignment = Enum.TextXAlignment.Left

			if font then
				textLabel.FontFace = font
			else
				textLabel.Font = Enum.Font.GothamBold
			end

			textLabel.Parent = parent
			return textLabel
		end

		local function slicedfn26()
			slicedfn25()
			screenGui = Instance.new("ScreenGui")
			screenGui.Name = slicedfn3()
			screenGui.Archivable = false
			screenGui.DisplayOrder = 58
			screenGui.IgnoreGuiInset = true
			screenGui.ResetOnSpawn = false
			screenGui.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
			frame = Instance.new("Frame")
			frame.Name = slicedfn3()
			frame.Active = true
			frame.BackgroundColor3 = Color3.fromRGB(24, 24, 28)
			frame.BackgroundTransparency = 0.28
			frame.BorderSizePixel = 0
			frame.Position = slicedfn20()
			frame.Size = UDim2.fromOffset(132, 34)
			frame.Parent = screenGui
			local uiCorner = Instance.new("UICorner")
			uiCorner.Name = slicedfn3()
			uiCorner.CornerRadius = UDim.new(0, 12)
			uiCorner.Parent = frame
			local uiStroke = Instance.new("UIStroke")
			uiStroke.Name = slicedfn3()
			uiStroke.Color = Color3.fromRGB(255, 255, 255)
			uiStroke.Thickness = 1
			uiStroke.Transparency = 0.9
			uiStroke.Parent = frame
			uiScale = Instance.new("UIScale")
			uiScale.Name = slicedfn3()
			uiScale.Parent = frame
			slicedfn24()
			sliced16 = createTextLabel(frame, 12, 34, color4)
			createTextLabel(frame, 48, 22, color7).Text = "FPS"
			local frame2 = Instance.new("Frame")
			frame2.Name = slicedfn3()
			frame2.AnchorPoint = Vector2.new(0.5, 0.5)
			frame2.BackgroundColor3 = Color3.fromRGB(255, 255, 255)
			frame2.BackgroundTransparency = 0.85
			frame2.BorderSizePixel = 0
			frame2.Position = UDim2.new(0, 74, 0.5, 0)
			frame2.Size = UDim2.fromOffset(1, 14)
			frame2.Parent = frame
			sliced17 = createTextLabel(frame, 82, 30, color4)
			createTextLabel(frame, 113, 14, color7).Text = "ms"
			screenGui.Parent = sliced3
			local currentCamera = workspace.CurrentCamera

			if currentCamera then
				tbl15[#tbl15 + 1] = currentCamera:GetPropertyChangedSignal("ViewportSize"):Connect(slicedfn24)
			end

			local flag6 = false
			local sliced20 = nil
			local vector2 = Vector2.zero
			local position = nil

			tbl15[#tbl15 + 1] = frame.InputBegan:Connect(function(input)
				if flag6 or input.UserInputState ~= Enum.UserInputState.Begin then
					return
				end
				local flag7 = input.UserInputType == Enum.UserInputType.Touch
				if not (input.UserInputType == Enum.UserInputType.MouseButton1) and not flag7 then
					return
				end
				flag6 = true
				sliced20 = flag7 and input or nil
				vector2 = Vector2.new(input.Position.X, input.Position.Y)
				position = frame.Position
			end)

			tbl15[#tbl15 + 1] = UserInputService.InputChanged:Connect(function(input)
				if not flag6 or not frame or not position then
					return
				end

				if not (sliced20 and input == sliced20 or not sliced20 and input.UserInputType == Enum.UserInputType.MouseMovement) then
					return
				end
				local slicedn21 = Vector2.new(input.Position.X, input.Position.Y) - vector2
				frame.Position = UDim2.new(position.X.Scale, position.X.Offset + slicedn21.X, position.Y.Scale, position.Y.Offset + slicedn21.Y)
			end)

			tbl15[#tbl15 + 1] = UserInputService.InputEnded:Connect(function(input)
				if not flag6 then
					return
				end

				if sliced20 and input == sliced20 or not sliced20 and input.UserInputType == Enum.UserInputType.MouseButton1 then
					flag6 = false
					sliced20 = nil
					position = nil

					if frame then
						slicedfn21(frame.Position)
					end
				end
			end)

			tbl15[#tbl15 + 1] = RunService.RenderStepped:Connect(function(deltaTime)
				if not flag5 or not sliced16 then
					return
				end
				local slicedn21 = math.clamp(deltaTime, 0.001, 1)
				local slicedn22 = 1 / slicedn21

				if slicedn19 <= 0 then
					slicedn19 = slicedn22
				else
					slicedn19 += (slicedn22 - slicedn19) * (1 - math.exp(-slicedn21 * slicedn17))
				end

				local now = os.clock()
				if now < slicedn20 then
					return
				end
				slicedn20 = now + slicedn16
				local slicedn23 = math.floor(slicedn19 + 0.5)
				local text = tostring(slicedn23)

				if text ~= sliced18 then
					sliced18 = text
					sliced16.Text = text
					sliced16.TextColor3 = slicedfn22(slicedn23)
				end

				local slicedn24 = 0

				pcall(function()
					slicedn24 = Stats.Network.ServerStatsItem["Data Ping"]:GetValue()
				end)

				local slicedn25 = math.floor(slicedn24 + 0.5)
				local text2 = tostring(slicedn25)

				if text2 ~= sliced19 then
					sliced19 = text2
					sliced17.Text = text2
					sliced17.TextColor3 = slicedfn23(slicedn25)
				end
			end)
		end

		sliced14:CreateSlider({
			Name = "FPS and Ping Size",
			Min = 60,
			Max = 160,
			Default = 100,
			AllowDecimals = false,
			Increment = 1,
			Unit = "%",
			SubOf = sliced14:CreateToggle({
				Name = "FPS and Ping",
				Default = false,
				Callback = function(arg)
					flag5 = arg == true

					if flag5 then
						slicedfn26()
					else
						slicedfn25()
					end
				end,
			}),
			Callback = function(arg)
				slicedn18 = math.clamp((tonumber(arg) or 100) / 100, 0.6, 1.6)
				slicedfn24()
			end,
		})

		slicedfn4(slicedfn25)
	end

	do
		local sliced15 = sliced13:CreateSection({ Name = "Utility", Expanded = true })
		local tbl15 = { Enabled = true, Alive = true, Silenced = {} }

		local function slicedfn20()
			if type(getconnections) ~= "function" then
				return {}
			end
			local ok, result = pcall(getconnections, localPlayer.Idled)
			return ok and type(result) == "table" and result or {}
		end

		local function slicedfn21()
			for _, sliced16 in ipairs(slicedfn20()) do
				if pcall(function()
					sliced16:Disable()
				end) then
					tbl15.Silenced[#tbl15.Silenced + 1] = sliced16
				end
			end
		end

		local function slicedfn22()
			local silenced = tbl15.Silenced

			if #silenced == 0 then
				silenced = slicedfn20()
			end

			for _, sliced16 in ipairs(silenced) do
				pcall(function()
					sliced16:Enable()
				end)
			end

			table.clear(tbl15.Silenced)
		end

		local obj = setmetatable({}, { __index = function()
			return function()
			end
		end })

		local tbl16 = {}

		local function slicedfn23()
			local tbl17 = {}
			if type(getgc) ~= "function" or type(debug) ~= "table" or type(debug.getupvalues) ~= "function" then
				return tbl17
			end
			local ok, result = pcall(getgc, false)
			if not ok or type(result) ~= "table" then
				return tbl17
			end

			for _, sliced16 in ipairs(result) do
				if type(sliced16) == "function" and islclosure(sliced16) then
					local ok2, result2 = pcall(debug.info, sliced16, "s")

					if ok2 and type(result2) == "string" and string.find(result2, "AntiAFK", 1, true) then
						local ok3, result3 = pcall(debug.getupvalues, sliced16)

						if ok3 and type(result3) == "table" then
							for k, sliced17 in pairs(result3) do
								if typeof(sliced17) == "Instance" and sliced17.ClassName == "TeleportService" then
									tbl17[#tbl17 + 1] = { Fn = sliced16, Index = k, Original = sliced17 }
								end
							end
						end
					end
				end
			end

			return tbl17
		end

		local function slicedfn24()
			for _, sliced16 in ipairs(slicedfn23()) do
				local ok, result = pcall(debug.getupvalue, sliced16.Fn, sliced16.Index)

				if ok and typeof(result) == "Instance" then
					if pcall(debug.setupvalue, sliced16.Fn, sliced16.Index, obj) then
						tbl16[#tbl16 + 1] = sliced16
					end
				end
			end
		end

		local function slicedfn25()
			for _, sliced16 in ipairs(tbl16) do
				pcall(debug.setupvalue, sliced16.Fn, sliced16.Index, sliced16.Original)
			end

			table.clear(tbl16)
		end

		local function slicedfn26()
			slicedfn21()

			if #tbl16 == 0 then
				slicedfn24()
			end
		end

		local connection = localPlayer.CharacterAdded:Connect(function()
			task.delay(1, function()
				if tbl15.Alive and tbl15.Enabled then
					table.clear(tbl15.Silenced)
					pcall(slicedfn26)
				end
			end)
		end)

		slicedfn4(function()
			pcall(function()
				connection:Disconnect()
			end)
		end)

		slicedfn4(function()
			tbl15.Alive = false
			slicedfn22()
			slicedfn25()
		end)

		task.spawn(function()
			while tbl15.Alive do
				if tbl15.Enabled then
					slicedfn26()
				end

				task.wait(600)
			end
		end)

		sliced15:CreateToggle({
			Name = "Anti AFK",
			Default = true,
			Callback = function(arg)
				tbl15.Enabled = arg ~= false

				if tbl15.Enabled then
					slicedfn26()
				else
					slicedfn22()
					slicedfn25()
				end
			end,
		})
	end

	TweenService = game:GetService("TweenService")
	GuiService = game:GetService("GuiService")
	StarterGui = game:GetService("StarterGui")
	antiGuard = tbl4.AntiGuard

	tbl14 = {
		Target = "line",
		LineOffset = 8,
		Height = 45,
		OffsetX = -90,
		OffsetZ = -35,
		Jitter = 0,
		Point = false,
		Disguise = true,
		Limp = true,
		Facing = "Zero",
		Freeze = false,
		StartAt = 0,
		Steps = {
			{ At = 0.1, To = "home" },
			{ At = 0.33, To = "home" },
			{ At = 0.56, To = "home" },
			{ At = 0.75, To = "start" },
		},
		ReleaseAt = 0.8,
		WeldScanGap = 0.03,
		BusyLimit = 2.5,
	}

	local function slicedfn20(arg, arg2, arg3, arg4, arg5, arg6)
		local tbl15 = {}

		for i = 1, arg do
			tbl15[#tbl15 + 1] = { At = arg2 + arg3 * (i - 1), To = "home" }
		end

		tbl15[#tbl15 + 1] = { At = arg4, To = "start" }

		return {
			Target = "home",
			LineOffset = 8,
			Height = 0,
			OffsetX = 0,
			OffsetZ = 0,
			Jitter = 0,
			Point = false,
			Disguise = true,
			Limp = false,
			Facing = "Zero",
			Freeze = true,
			StartAt = 0,
			StartRandom = 0,
			HopRandom = 0.085,
			HoldRandom = 0.395,
			Steps = tbl15,
			ReleaseAt = arg5,
			WeldScanGap = 0.03,
			BusyLimit = arg6,
		}
	end

	SourcesAntiGuard = { LightDark = tbl14, Default = slicedfn20(25, 0, 0.05, 1.27, 1.52, 2.5) }
end

pcall(function()
	getgenv().SourcesAntiGuard = SourcesAntiGuard
end)

local tbl15

tbl15 = {
	Card = Color3.fromRGB(8, 2, 2),
	CardTop = Color3.fromRGB(40, 8, 8),
	Stroke = Color3.fromRGB(140, 25, 25),
	Text = Color3.fromRGB(255, 240, 240),
	AccentA = Color3.fromRGB(220, 40, 40),
	AccentB = Color3.fromRGB(255, 90, 90),
	Good = Color3.fromRGB(80, 220, 140),
	Work = Color3.fromRGB(255, 190, 70),
	Bad = Color3.fromRGB(240, 90, 90),
	Off = Color3.fromRGB(58, 40, 40),
}

local tbl16

tbl16 = {
	{ Path = { "GearGiver_Slap", "Podium" }, Offset = Vector3.new(-16.415, 21.072, -6.106) },
	{
		Path = { "World", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" },
		Offset = Vector3.new(-26.776, 1.75, 18.665),
	},
	{
		Path = { "__OBJECTS", "Machines", "RiftMachine", "Rift", "Meshes/VoidPortal_Cube.003" },
		Offset = Vector3.new(-26.776, 1.75, 18.665),
	},
}

local slicedn4 = 52
local flag4 = true
local tbl17 = {}
local tbl18

tbl18 = {
	AreaId = nil,
	SignalCarrying = false,
	WeldCarrying = false,
	Carrying = false,
	Active = false,
	Disguise = nil,
	FlashRequest = nil,
	FlashUntil = 0,
}

local slicedfn19

slicedfn19 = function()
	local tbl19 = {}

	for i = 1, math.random(10, 16) do
		tbl19[i] = string.char(math.random(97, 122))
	end

	return table.concat(tbl19)
end

local hui = nil

pcall(function()
	hui = gethui()
end)

hui = hui or CoreGui
local slicedfn20

slicedfn20 = function(arg, parent, arg2)
	local instance = Instance.new(arg)
	instance.Name = slicedfn19()
	local pairs = pairs
	local tbl19 = arg2 or {}

	for k, sliced11 in pairs(tbl19) do
		instance[k] = sliced11
	end

	instance.Parent = parent
	return instance
end

local slicedfn21

slicedfn21 = function(arg, arg2, arg3, arg4)
	local ok, result = pcall(function()
		local sliced10 = TweenService
		local create = sliced10.Create
		local tweenInfo = TweenInfo.new
		local sliced11 = arg4
		local quint

		if arg4 then
			quint = sliced11
		else
			quint = Enum.EasingStyle.Quint
		end

		return create(sliced10, arg, tweenInfo(arg2, quint, Enum.EasingDirection.Out), arg3)
	end)

	if ok and result then
		result:Play()
	end
end

local ScreenGui

ScreenGui = slicedfn20("ScreenGui", nil, {
	ResetOnSpawn = false,
	IgnoreGuiInset = true,
	DisplayOrder = -100,
	ZIndexBehavior = Enum.ZIndexBehavior.Sibling,
})

local Frame

Frame = slicedfn20("Frame", ScreenGui, {
	AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.new(0.5, 0, 1, -120),
	Size = UDim2.fromOffset(226, 52),
	BackgroundTransparency = 1,
})

local UIScale = slicedfn20("UIScale", Frame, { Scale = 1 })
local Frame2 = slicedfn20("Frame", Frame, { Size = UDim2.fromScale(1, 1), BackgroundColor3 = tbl15.Card, BorderSizePixel = 0, Active = true })
slicedfn20("UICorner", Frame2, { CornerRadius = UDim.new(0, 14) })
local UIScale2 = slicedfn20("UIScale", Frame2, { Scale = 0.86 })
slicedfn20("UIGradient", Frame2, { Color = ColorSequence.new(tbl15.CardTop, tbl15.Card), Rotation = 90 })
local UIGradient, Frame3, render, slicedfn22

do
	local UIStroke = slicedfn20("UIStroke", Frame2, {
		Thickness = 1.5,
		Color = Color3.fromRGB(255, 255, 255),
		Transparency = 0.2,
		ApplyStrokeMode = Enum.ApplyStrokeMode.Border,
	})

	UIGradient = slicedfn20("UIGradient", UIStroke, { Color = ColorSequence.new(tbl15.Stroke, tbl15.Stroke) })

	Frame3 = slicedfn20("Frame", Frame2, {
		AnchorPoint = Vector2.new(0, 0.5),
		Position = UDim2.new(0, 10, 0.5, 0),
		Size = UDim2.fromOffset(36, 36),
		BackgroundColor3 = Color3.fromRGB(12, 4, 4),
		BorderSizePixel = 0,
		ZIndex = 2,
	})

	slicedfn20("UICorner", Frame3, { CornerRadius = UDim.new(0, 11) })
	local UIStroke2 = slicedfn20("UIStroke", Frame3, { Thickness = 1.5, Color = tbl15.Off, ApplyStrokeMode = Enum.ApplyStrokeMode.Border })

	local ImageLabel = slicedfn20("ImageLabel", Frame3, {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromScale(0.86, 0.86),
		BackgroundTransparency = 1,
		Image = "",
		ImageTransparency = 0.35,
		ScaleType = Enum.ScaleType.Crop,
		ZIndex = 3,
	})

	slicedfn20("UICorner", ImageLabel, { CornerRadius = UDim.new(0, 8) })

	-- Sources Hub logo
	local moonDisc = slicedfn20("ImageLabel", Frame3, {
		AnchorPoint = Vector2.new(0.5, 0.5),
		Position = UDim2.fromScale(0.5, 0.5),
		Size = UDim2.fromOffset(28, 28),
		BackgroundTransparency = 1,
		Image = "rbxassetid://111331179075915",
		ScaleType = Enum.ScaleType.Fit,
		ZIndex = 3,
	})
	local UIScale3 = slicedfn20("UIScale", ImageLabel, { Scale = 1 })
	local color3 = Color3.fromRGB

	slicedfn20("UIGradient", slicedfn20("TextLabel", Frame2, {
		BackgroundTransparency = 1,
		Position = UDim2.new(0, 56, 0, 7),
		Size = UDim2.new(1, -112, 0, 15),
		Font = Enum.Font.GothamBold,
		TextSize = 13,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextColor3 = Color3.fromRGB(255, 255, 255),
		Text = "Sources Hub",
		ZIndex = 2,
	}), { Color = ColorSequence.new(Color3.fromRGB(255, 90, 90), Color3.fromRGB(255, 176, 176)) })

	local guardTitle = slicedfn20("TextLabel", Frame2, {
		BackgroundTransparency = 1,
		Position = UDim2.new(0, 56, 0, 22),
		Size = UDim2.new(1, -112, 0, 20),
		Font = Enum.Font.GothamBold,
		TextSize = 15,
		TextXAlignment = Enum.TextXAlignment.Left,
		TextColor3 = tbl15.Text,
		Text = "Anti Guard",
		ZIndex = 2,
	})
	slicedfn20("UIGradient", guardTitle, { Color = ColorSequence.new(Color3.fromRGB(255, 176, 176), Color3.fromRGB(255, 90, 90)) })

	local TextButton = slicedfn20("TextButton", Frame2, {
		AnchorPoint = Vector2.new(1, 0.5),
		Position = UDim2.new(1, -12, 0.5, 0),
		Size = UDim2.fromOffset(42, 22),
		BackgroundColor3 = Color3.fromRGB(255, 255, 255),
		AutoButtonColor = false,
		BorderSizePixel = 0,
		Text = "",
		ZIndex = 2,
	})

	slicedfn20("UICorner", TextButton, { CornerRadius = UDim.new(1, 0) })
	local UIGradient2 = slicedfn20("UIGradient", TextButton, { Color = ColorSequence.new(tbl15.Off, tbl15.Off) })

	local Frame4 = slicedfn20("Frame", TextButton, {
		AnchorPoint = Vector2.new(0, 0.5),
		Position = UDim2.new(0, 3, 0.5, 0),
		Size = UDim2.fromOffset(16, 16),
		BackgroundColor3 = Color3.fromRGB(245, 245, 250),
		BorderSizePixel = 0,
		ZIndex = 3,
	})

	slicedfn20("UICorner", Frame4, { CornerRadius = UDim.new(1, 0) })

	local function slicedfn23()
		return antiGuard.Enabled and tbl15.AccentA or tbl15.Off
	end

	render = function(arg)
		local slicedn5 = arg and 0 or 0.28

		if antiGuard.Enabled then
			UIGradient2.Color = ColorSequence.new(tbl15.AccentA, tbl15.AccentB)
			local sliced10 = UIGradient
			local colorSequence = ColorSequence.new
			local tbl19 = {}
			local sliced11 = ColorSequenceKeypoint.new(0, tbl15.Stroke)
			local sliced12 = ColorSequenceKeypoint.new(0.45, tbl15.AccentA)
			local sliced13 = ColorSequenceKeypoint.new(0.55, tbl15.AccentB)
			local new = ColorSequenceKeypoint.new
			local stroke = tbl15.Stroke
			tbl19[1] = sliced11
			tbl19[2] = sliced12
			tbl19[3] = sliced13

			do
				local values = table.pack(new(1, stroke))
				table.move(values, 1, values.n, 4, tbl19)
			end

			sliced10.Color = colorSequence(tbl19)
			slicedfn21(Frame4, slicedn5, { Position = UDim2.new(1, -19, 0.5, 0) }, Enum.EasingStyle.Back)
			slicedfn21(ImageLabel, slicedn5, { ImageTransparency = 0 })
			slicedfn21(UIStroke, 0.3, { Transparency = 0 })
		else
			UIGradient2.Color = ColorSequence.new(tbl15.Off, tbl15.Off)
			UIGradient.Color = ColorSequence.new(tbl15.Stroke, tbl15.Stroke)
			slicedfn21(Frame4, slicedn5, { Position = UDim2.new(0, 3, 0.5, 0) }, Enum.EasingStyle.Back)
			slicedfn21(ImageLabel, slicedn5, { ImageTransparency = 0.35 })
			slicedfn21(UIStroke, 0.3, { Transparency = 0.2 })
		end

		if tbl18.FlashUntil <= os.clock() then
			slicedfn21(UIStroke2, slicedn5, { Color = slicedfn23() })
		end
	end

	slicedfn22 = function(arg, arg2)
		tbl18.FlashRequest = { Color = arg, Hold = arg2 }
	end

	local function slicedfn24()
		local flashRequest = tbl18.FlashRequest
		if not flashRequest then
			return
		end
		tbl18.FlashRequest = nil
		tbl18.FlashUntil = os.clock() + (flashRequest.Hold or 0)
		slicedfn21(UIStroke2, 0.2, { Color = flashRequest.Color })

		if flashRequest.Hold then
			task.delay(flashRequest.Hold, function()
				local flag5 = flag4

				if flag4 then
					local flashUntil = tbl18.FlashUntil
					flag5 = os.clock() >= flashUntil
				end

				if flag5 then
					slicedfn21(UIStroke2, 0.3, { Color = slicedfn23() })
				end
			end)
		end
	end

	local function slicedfn25(arg)
		local handle = antiGuard.Handle
		if type(handle) ~= "table" then
			return
		end

		for _, sliced10 in ipairs({ "Set", "SetValue" }) do
			local ok, result = pcall(function()
				return handle[sliced10]
			end)

			if ok and type(result) == "function" and pcall(result, handle, arg) then
				return
			end
		end
	end

	antiGuard.Render = render

	local TextButton2 = slicedfn20("TextButton", Frame2, {
		Size = UDim2.fromScale(1, 1),
		BackgroundTransparency = 1,
		AutoButtonColor = false,
		Text = "",
		ZIndex = 10,
	})

	tbl17[#tbl17 + 1] = TextButton2.MouseButton1Click:Connect(function()
		antiGuard.Enabled = not antiGuard.Enabled
		render(false)
		slicedfn25(antiGuard.Enabled)
		slicedfn21(UIScale3, 0.12, { Scale = 1.15 })

		task.delay(0.12, function()
			if flag4 then
				slicedfn21(UIScale3, 0.3, { Scale = 1 }, Enum.EasingStyle.Back)
			end
		end)
	end)

	local size = TextButton.Size

	tbl17[#tbl17 + 1] = TextButton2.MouseEnter:Connect(function()
		slicedfn21(TextButton, 0.15, { Size = size + UDim2.fromOffset(2, 2) })
	end)

	tbl17[#tbl17 + 1] = TextButton2.MouseLeave:Connect(function()
		slicedfn21(TextButton, 0.15, { Size = size })
	end)

	local tbl19 = {
		Hotbar = true,
		HotBar = true,
		Toolbar = true,
		ToolBar = true,
		Backpack = true,
		Inventory = true,
	}

	local tbl20 = {}
	local huge = math.huge
	local huge2 = math.huge
	local rotation = 0
	local slicedn5 = nil

	local function slicedfn26(arg)
		while arg do
			if arg:IsA("GuiObject") and not arg.Visible then
				return false
			end

			if arg:IsA("LayerCollector") then
				return arg.Enabled
			end
			arg = arg.Parent
		end

		return false
	end

	local function slicedfn27()
		local ok, result = pcall(function()
			return GuiService:GetGuiInset().Y
		end)

		return ok and result or 0
	end

	local function slicedfn28(arg)
		local sliced10 = nil

		for _, descendant in ipairs(arg:GetDescendants()) do
			if descendant:IsA("GuiButton") and descendant.Visible and descendant.AbsoluteSize.Y > 8 and descendant.AbsoluteSize.X > 8 then
				local y = descendant.AbsolutePosition.Y

				if not sliced10 or y < sliced10 then
					sliced10 = y
				end
			end
		end

		return sliced10 or arg.AbsolutePosition.Y
	end

	local function slicedfn29()
		table.clear(tbl20)
		local playerGui = localPlayer:FindFirstChildOfClass("PlayerGui")
		if not playerGui then
			return
		end

		for _, descendant in ipairs(playerGui:GetDescendants()) do
			if descendant:IsA("GuiObject") and tbl19[descendant.Name] then
				tbl20[#tbl20 + 1] = descendant
			end
		end
	end

	local function slicedfn30()
		local tbl21 = {}

		pcall(function()
			if not StarterGui:GetCoreGuiEnabled(Enum.CoreGuiType.Backpack) then
				return
			end

			for _, child in ipairs(CoreGui.RobloxGui.Backpack:GetChildren()) do
				if child:IsA("GuiObject") then
					tbl21[#tbl21 + 1] = child
				end
			end
		end)

		for _, sliced10 in ipairs(tbl20) do
			if sliced10.Parent then
				tbl21[#tbl21 + 1] = sliced10
			end
		end

		return tbl21
	end

	local function slicedfn31()
		local currentCamera = workspace.CurrentCamera
		if not currentCamera then
			return
		end
		local viewportSize = currentCamera.ViewportSize
		if viewportSize.X < 10 or viewportSize.Y < 10 then
			return
		end
		local flag5 = UserInputService.TouchEnabled and not UserInputService.KeyboardEnabled
		local slicedn6 = math.min(viewportSize.X / 1280, viewportSize.Y / 720)
		local scale = (flag5 and math.clamp(slicedn6 * 1.05, 0.6, 0.8) * 0.97 or math.clamp(slicedn6, 0.8, 1.1)) * 1.2
		UIScale.Scale = scale
		local backgroundTransparency = flag5 and 0.3 or 0

		if Frame2.BackgroundTransparency ~= backgroundTransparency then
			Frame2.BackgroundTransparency = backgroundTransparency
			Frame3.BackgroundTransparency = backgroundTransparency
		end

		local slicedn7 = viewportSize.Y - 8 * scale
		local flag6 = false

		for _, sliced10 in ipairs(slicedfn30()) do
			local ok, result = pcall(slicedfn26, sliced10)

			if ok and result then
				local absoluteSize = sliced10.AbsoluteSize
				local y = sliced10.AbsolutePosition.Y

				if absoluteSize.X > 20 and absoluteSize.Y > 20 and absoluteSize.Y < viewportSize.Y * 0.4 and y + absoluteSize.Y / 2 > viewportSize.Y * 0.5 then
					local ok2, result2 = pcall(slicedfn28, sliced10)
					y = ok2 and result2 or y
					flag6 = true
					slicedn7 = math.min(slicedn7, y + slicedfn27(sliced10))
				end
			end
		end

		if flag6 then
			slicedn5 = viewportSize.Y - slicedn7
		elseif slicedn5 then
			slicedn7 = viewportSize.Y - slicedn5
		end

		local slicedn8 = math.max(slicedn7 - (flag5 and 4 or 6) * scale - slicedn4 * scale / 2, slicedn4 * scale / 2 + 8)
		Frame.Position = UDim2.new(0.5, 0, 0, slicedn8)
	end

	tbl17[#tbl17 + 1] = RunService.RenderStepped:Connect(function(deltaTime)
		slicedfn24()
		huge += deltaTime
		huge2 += deltaTime

		if huge >= 3 then
			huge = 0
			pcall(slicedfn29)
		end

		if huge2 >= 0.2 then
			huge2 = 0
			pcall(slicedfn31)
		end

		if antiGuard.Enabled and not SourcesLib.NoAnim then
			rotation = (rotation + deltaTime * (tbl18.Active and 360 or 90)) % 360
			UIGradient.Rotation = rotation
		end
	end)
end

render(true)

antiGuard.ShowPanel = function(arg)
	ScreenGui.Enabled = arg == true
end

SourcesLib.ThemeHooks[#SourcesLib.ThemeHooks + 1] = function(mapColor, mapSeq, recolorTree)
	for _, key in ipairs({ "Card", "CardTop", "Stroke", "AccentA", "AccentB" }) do
		tbl15[key] = mapColor(tbl15[key])
	end
	pcall(recolorTree, ScreenGui)
	pcall(render, false)
end
SourcesLib.RunThemeHooksFrom("Moon")

ScreenGui.Enabled = antiGuard.PanelShown == true
ScreenGui.Parent = hui
slicedfn21(UIScale2, 0.45, { Scale = 1 }, Enum.EasingStyle.Back)
local slicedfn23

slicedfn23 = function()
	local sliced10 = tbl4.Root()
	if not sliced10 then
		return nil
	end

	for _, child in ipairs(workspace:GetChildren()) do
		if child:IsA("Model") and child:FindFirstChild("Hitbox") then
			for _, descendant in ipairs(child:GetDescendants()) do
				if descendant:IsA("JointInstance") or descendant:IsA("WeldConstraint") or descendant:IsA("RigidConstraint") then
					local ok, result, result2 = pcall(function()
						return descendant.Part0, descendant.Part1
					end)

					if ok and (result == sliced10 or result2 == sliced10) then
						return child
					end
				end
			end
		end
	end

	return nil
end

local slicedfn24

do
	local function slicedfn25(arg, parent)
		local tbl19 = {}

		for _, descendant in ipairs(arg:GetDescendants()) do
			tbl19[descendant] = descendant.Archivable

			pcall(function()
				descendant.Archivable = true
			end)
		end

		local archivable = arg.Archivable
		arg.Archivable = true

		local ok, result = pcall(function()
			return arg:Clone()
		end)

		arg.Archivable = archivable

		for k, sliced10 in pairs(tbl19) do
			pcall(function()
				k.Archivable = sliced10
			end)
		end

		if not ok or not result then
			return nil
		end
		result.Name = slicedfn19()

		for _, descendant in ipairs(result:GetDescendants()) do
			if descendant:IsA("LuaSourceContainer") or descendant:IsA("Sound") or descendant:IsA("ForceField") or descendant:IsA("JointInstance") or descendant:IsA("Constraint") or descendant:IsA("WeldConstraint") or descendant:IsA("BodyMover") or descendant:IsA("ProximityPrompt") or descendant:IsA("BillboardGui") then
				pcall(function()
					descendant:Destroy()
				end)
			elseif descendant:IsA("BasePart") then
				descendant.Anchored = true
				descendant.CanCollide = false
				descendant.CanQuery = false
				descendant.CanTouch = false
			elseif descendant:IsA("Humanoid") then
				descendant.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
				descendant.HealthDisplayType = Enum.HumanoidHealthDisplayType.AlwaysOff
			end
		end

		result.Parent = parent
		return result
	end

	local function slicedfn26(arg, arg2)
		local currentCamera = workspace.CurrentCamera
		-- the camera lock of Anti Guard only exists in Instant TP
		if not arg or not currentCamera or tbl18.Disguise or not tbl4.SafeCarry.Teleport then
			return
		end
		arg2 = arg2 or Vector3.zero
		local disguise = { Camera = currentCamera, CameraType = currentCamera.CameraType, CameraCFrame = currentCamera.CFrame, Copies = {}, Hidden = {} }
		tbl18.Disguise = disguise
		task.delay(14, function()
			if tbl18.Disguise == disguise then
				slicedfn24()
			end
		end)
		local tbl19 = { arg }
		local ok, result = pcall(slicedfn23)

		if ok and result then
			tbl19[#tbl19 + 1] = result
		end

		for _, sliced10 in ipairs(tbl19) do
			for _, descendant in ipairs(sliced10:GetDescendants()) do
				if descendant:IsA("BasePart") or descendant:IsA("Decal") or descendant:IsA("Texture") then
					disguise.Hidden[#disguise.Hidden + 1] = descendant
				end
			end
		end

		local function slicedfn27()
			for _, sliced10 in ipairs(disguise.Hidden) do
				pcall(function()
					sliced10.LocalTransparencyModifier = 1
				end)
			end

			pcall(function()
				if currentCamera.CameraType ~= Enum.CameraType.Scriptable then
					currentCamera.CameraType = Enum.CameraType.Scriptable
				end

				currentCamera.CFrame = disguise.CameraCFrame
			end)
		end

		slicedfn27()
		disguise.BindName = slicedfn19()

		if not pcall(function()
			RunService:BindToRenderStep(disguise.BindName, Enum.RenderPriority.Last.Value + 1, slicedfn27)
		end) then
			disguise.BindName = nil
			disguise.Link = RunService.RenderStepped:Connect(slicedfn27)
		end

		disguise.Beat = RunService.Heartbeat:Connect(slicedfn27)

		for _, sliced10 in ipairs(tbl19) do
			local ok2, result2 = pcall(slicedfn25, sliced10, currentCamera)

			if ok2 and result2 then
				if arg2.Magnitude > 0.01 then
					for _, descendant in ipairs(result2:GetDescendants()) do
						if descendant:IsA("BasePart") then
							pcall(function()
								descendant.CFrame = descendant.CFrame + arg2
							end)
						end
					end
				end

				disguise.Copies[#disguise.Copies + 1] = result2
			end
		end
	end

	SourcesLib.ReleaseCamera = function()
		slicedfn24()
	end

	slicedfn24 = function()
		local disguise = tbl18.Disguise
		if not disguise then
			return
		end
		tbl18.Disguise = nil

		if disguise.BindName then
			pcall(function()
				RunService:UnbindFromRenderStep(disguise.BindName)
			end)
		end

		if disguise.Link then
			pcall(function()
				disguise.Link:Disconnect()
			end)
		end

		if disguise.Beat then
			pcall(function()
				disguise.Beat:Disconnect()
			end)
		end

		for _, sliced10 in ipairs(disguise.Hidden) do
			pcall(function()
				sliced10.LocalTransparencyModifier = 0
			end)
		end

		pcall(function()
			disguise.Camera.CameraType = disguise.CameraType
		end)

		for _, copy in ipairs(disguise.Copies) do
			pcall(function()
				copy:Destroy()
			end)
		end
	end

	local function slicedfn27()
		for _, sliced10 in ipairs(tbl16) do
			local sliced11 = workspace

			for _, sliced12 in ipairs(sliced10.Path) do
				sliced11 = sliced11 and sliced11:FindFirstChild(sliced12) or nil
			end

			if sliced11 and sliced11:IsA("BasePart") then
				return sliced11.CFrame:PointToWorldSpace(sliced10.Offset)
			end
		end

		return Vector3.new(528.7, 70.57, -364.11)
	end

	local function slicedfn28(arg, arg2, arg3, arg4, arg5)
		local cFrame = CFrame.new(arg3) * arg4

		pcall(function()
			arg:PivotTo(cFrame)
		end)

		if (arg2.Position - arg3).Magnitude > 3 then
			pcall(function()
				arg2.CFrame = cFrame
			end)
		end

		if arg5 == false then
			return
		end

		for _, descendant in ipairs(arg:GetDescendants()) do
			if descendant:IsA("BasePart") then
				pcall(function()
					descendant.AssemblyLinearVelocity = Vector3.zero
					descendant.AssemblyAngularVelocity = Vector3.zero
				end)
			end
		end
	end

	local function slicedfn29()
		local areaId = tbl18.AreaId

		if type(areaId) ~= "string" or areaId == "" then
			areaId = type(tbl4.Steal) == "table" and tbl4.Steal.CarryAreaId or nil
		end

		if type(areaId) ~= "string" or areaId == "" then
			local attribute = localPlayer:GetAttribute("AreaId")
			areaId = type(attribute) == "string" and attribute or nil
		end

		return areaId
	end

	local tbl19 = { lightdark = "LightDark" }

	local function slicedfn30(arg)
		if type(arg) ~= "string" then
			return "Default"
		end
		local lower = string.lower
		local sliced10 = string.gsub(arg, "[^%a]", "")
		return tbl19[lower(sliced10)] or "Default"
	end

	antiGuard.ProfileName = function()
		return slicedfn30(slicedfn29())
	end

	local function slicedfn31()
		local ok, result = pcall(function()
			return getgenv().SourcesAntiGuard
		end)

		if ok and type(result) == "table" then
			if type(result.Steps) == "table" then
				return result
			end
			local default = result[slicedfn30(slicedfn29())] or result.Default
			if type(default) == "table" then
				return default
			end
		end

		return SourcesAntiGuard[slicedfn30(slicedfn29())] or tbl14
	end

	local function slicedfn32()
		local sliced10 = slicedfn31()
		local options = antiGuard.Options

		-- Instant TP / Delivery Stop: Anti Guard stops in front of the line and stays there (no return to the start),
		-- then the delivery takes over from there
		if tbl4.SafeCarry.LineDrop then
			options = { Destination = "Next To Line", Stay = true, LineOffset = 14 }
		end
		if type(options) ~= "table" or options.Destination == "Safe Zone" and not options.Stay then
			return sliced10
		end
		local tbl20 = {}

		for k, sliced11 in pairs(sliced10) do
			tbl20[k] = sliced11
		end

		if options.Destination == "Next To Line" then
			tbl20.Target = "edge"
			tbl20.LineOffset = options.LineOffset or 6
			tbl20.Height = 0
			tbl20.OffsetX = 0
			tbl20.OffsetZ = 0
		elseif options.Destination == "Saved Spot" and typeof(options.Spot) == "Vector3" then
			tbl20.Target = "point"
			tbl20.Point = options.Spot
			tbl20.Height = 0
			tbl20.OffsetX = 0
			tbl20.OffsetZ = 0
		end

		if options.Stay and type(sliced10.Steps) == "table" then
			local steps = {}

			for _, step in ipairs(sliced10.Steps) do
				if type(step) == "table" and step.To ~= "start" then
					steps[#steps + 1] = step
				end
			end

			tbl20.Steps = steps
		end

		-- Instant TP: the guard run is squeezed to half the time so the guard has no time to hit us
		if tbl4.SafeCarry.Teleport and type(tbl20.Steps) == "table" then
			local fast = {}
			local lastAt = 0

			for i, step in ipairs(tbl20.Steps) do
				local at = (tonumber(step.At) or 0) * 0.5
				lastAt = math.max(lastAt, at)
				fast[i] = { At = at, To = step.To, Glide = step.Glide }
			end

			tbl20.Steps = fast
			tbl20.ReleaseAt = lastAt + 0.1
			tbl20.HopRandom = math.min(tonumber(tbl20.HopRandom) or 0, 0.02)
			tbl20.HoldRandom = math.min(tonumber(tbl20.HoldRandom) or 0, 0.05)
		end

		return tbl20
	end

	local function slicedfn33(arg, arg2)
		local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
		world = world and world:FindFirstChild("Areas")
		world = world and world:FindFirstChild("SeparationLine")

		if world and world:IsA("BasePart") then
			local cFrame = world.CFrame
			local sliced10 = (Vector3.new(0, 1, 0)):Cross(world.Size.X >= world.Size.Z and cFrame.RightVector or cFrame.LookVector)
			local vector = Vector3.new(sliced10.X, 0, sliced10.Z)

			if vector.Magnitude > 0.001 then
				local unit = vector.Unit
				local slicedn5 = cFrame.Position + ((arg2 - cFrame.Position):Dot(unit) >= 0 and -unit or unit) * (tonumber(arg.LineOffset) or 8)
				return Vector3.new(slicedn5.X, arg2.Y + 0.5, slicedn5.Z)
			end
		end

		return nil
	end

	local function slicedfn34(arg, arg2)
		local str = tostring(arg.Target or "home")
		if str == "sky" then
			return arg2
		end

		if str == "point" then
			if typeof(arg.Point) == "Vector3" then
				return arg.Point
			end
			return arg2
		end

		if str == "line" then
			local sliced10 = slicedfn33(arg, arg2)
			if sliced10 then
				return sliced10
			end
		end

		if str == "edge" then
			local world = workspace:FindFirstChild("World") or workspace:FindFirstChild("__OBJECTS")
			world = world and world:FindFirstChild("Areas")
			world = world and world:FindFirstChild("SeparationLine")

			if world and world:IsA("BasePart") then
				local cFrame = world.CFrame
				local rightVector = world.Size.X >= world.Size.Z and cFrame.RightVector or cFrame.LookVector
				local vector = Vector3.new(rightVector.X, 0, rightVector.Z)
				local sliced10 = (Vector3.new(0, 1, 0)):Cross(vector)
				local vector2 = Vector3.new(sliced10.X, 0, sliced10.Z)

				if vector2.Magnitude > 0.001 and vector.Magnitude > 0.001 then
					local unit = vector.Unit
					local unit2 = vector2.Unit
					local slicedn5 = arg2 - cFrame.Position
					local slicedn6 = -world.Size.Magnitude / 2
					local slicedn7 = world.Size.Magnitude / 2
					local slicedn8 = cFrame.Position + unit * math.clamp(slicedn5:Dot(unit), slicedn6, slicedn7) + (slicedn5:Dot(unit2) >= 0 and unit2 or -unit2) * (tonumber(arg.LineOffset) or 6)
					local sliced11 = slicedfn27()
					return Vector3.new(slicedn8.X, (sliced11 and sliced11.Y or arg2.Y) + 3, slicedn8.Z)
				end
			end
		end

		return slicedfn27()
	end

	local function slicedfn35(arg, arg2)
		return slicedfn34(arg, arg2) + Vector3.new(tonumber(arg.OffsetX) or 0, tonumber(arg.Height) or 0, tonumber(arg.OffsetZ) or 0)
	end

	local function slicedfn36()
		tbl18.Active = false
		antiGuard.Busy = false
	end

	local function slicedfn37(arg)
		local slicedn5 = math.max(tonumber(arg) or 0, 0)
		if slicedn5 <= 0 then
			return 0
		end
		return (math.random() * 2 - 1) * slicedn5
	end

	local function slicedfn38(arg)
		local steps = type(arg.Steps) == "table" and arg.Steps or {}
		local slicedn5 = tonumber(arg.ReleaseAt) or 0
		local slicedn6 = math.max(tonumber(arg.StartAt) or 0, 0)
		local slicedn7 = math.max(tonumber(arg.StartRandom) or 0, 0)
		local slicedn8 = math.max(tonumber(arg.HopRandom) or 0, 0)
		local slicedn9 = math.max(tonumber(arg.HoldRandom) or 0, 0)
		if slicedn7 <= 0 and slicedn8 <= 0 and slicedn9 <= 0 then
			return steps, slicedn5, slicedn6
		end
		local slicedn10 = math.max(slicedn6 + slicedfn37(slicedn7), 0)
		local tbl20 = {}
		local slicedn11 = 0
		local slicedn12 = 0

		for i, step in ipairs(steps) do
			if type(step) == "table" then
				local slicedn13 = math.max(tonumber(step.At) or 0, 0)
				slicedn12 = math.max(slicedn12 + math.max(slicedn13 - slicedn11, 0) + slicedfn37(step.To == "start" and slicedn9 or slicedn8), slicedn10)
				tbl20[i] = { At = slicedn12, To = step.To, Glide = step.Glide }
				slicedn11 = slicedn13
				continue
			end

			break
		end

		return tbl20, slicedn12 + math.max(slicedn5 - slicedn11, 0), slicedn10
	end

	local function slicedfn39(arg)
		local character = localPlayer.Character
		local sliced10 = tbl4.Root()
		local humanoid = character and character:FindFirstChildOfClass("Humanoid")

		if not sliced10 or not humanoid or humanoid.Health <= 0 then
			slicedfn36()
			slicedfn22(tbl15.Bad, 1.6)
			return
		end

		local function slicedfn40()
			return flag4 and sliced10.Parent ~= nil and humanoid.Parent ~= nil and humanoid.Health > 0
		end

		local platformStand = humanoid.PlatformStand
		local cFrame = sliced10.CFrame
		local position = cFrame.Position
		local sliced11 = slicedfn32()
		local sliced12, sliced13, sliced14 = slicedfn38(sliced11)
		local flag5 = sliced11.Freeze ~= false
		local str = tostring(sliced11.Facing or "Keep")
		local slicedn5 = math.max(tonumber(sliced11.Jitter) or 0, 0)
		local cframe = str == "Zero" and CFrame.new() or cFrame.Rotation

		local function slicedfn41()
			if str == "Spin" then
				return CFrame.Angles(0, math.rad(math.random(0, 359)), 0)
			end
			return cframe
		end

		local function slicedfn42(arg2)
			if slicedn5 <= 0 then
				return arg2
			end
			return arg2 + Vector3.new((math.random() * 2 - 1) * slicedn5, 0, (math.random() * 2 - 1) * slicedn5)
		end

		local sliced15 = slicedfn35(sliced11, position)

		local function slicedfn43(arg2)
			while slicedfn40() and os.clock() - arg < arg2 do
				RunService.Heartbeat:Wait()

				if flag5 then
					pcall(function()
						sliced10.AssemblyLinearVelocity = Vector3.zero
						sliced10.AssemblyAngularVelocity = Vector3.zero
					end)
				end
			end

			return slicedfn40()
		end

		local function slicedfn44(arg2, arg3)
			slicedfn28(character, sliced10, arg2, arg3, flag5)
			RunService.PreSimulation:Wait()

			if slicedfn40() and (sliced10.Position - arg2).Magnitude > 3 then
				slicedfn28(character, sliced10, arg2, arg3, flag5)
			end
		end

		pcall(function()
			humanoid.BreakJointsOnDeath = false
		end)

		if sliced11.Disguise ~= false then
			pcall(slicedfn26, character, Vector3.zero)
		end

		slicedfn22(tbl15.Work)

		if slicedfn43(sliced14) and sliced11.Limp ~= false then
			humanoid.PlatformStand = true
		end

		local sliced16 = position

		for _, sliced17 in ipairs(sliced12) do
			local flag6 = type(sliced17) ~= "table"

			if not flag6 then
				flag6 = not slicedfn43(tonumber(sliced17.At) or 0)
			end

			if not flag6 then
				local flag7 = sliced17.To == "start" and position or slicedfn42(sliced15)
				local sliced18 = slicedfn41()

				if type(sliced17.Glide) == "table" and #sliced17.Glide > 0 then
					for _, sliced19 in ipairs(sliced17.Glide) do
						if slicedfn40() then
							local clamp = math.clamp
							local slicedn6 = tonumber(sliced19) or 1
							local sliced20 = slicedfn28
							local sliced21 = clamp(slicedn6, 0, 1)
							sliced20(character, sliced10, sliced16:Lerp(flag7, sliced21), sliced18, flag5)
							RunService.Heartbeat:Wait()
							continue
						end

						break
					end

					sliced16 = flag7
				else
					slicedfn44(flag7, sliced18)
					sliced16 = flag7
				end

				continue
			end

			break
		end

		slicedfn43(sliced13)

		pcall(function()
			humanoid.PlatformStand = platformStand
		end)

		slicedfn24()
		slicedfn36()

		if slicedfn40() and tbl18.Carrying then
			slicedfn22(tbl15.Good, 1.6)
		else
			slicedfn22(tbl15.Bad, 1.6)
		end
	end

	local function slicedfn40(arg)
		if not pcall(slicedfn39, arg) then
			pcall(function()
				local character = localPlayer.Character
				character = character and character:FindFirstChildOfClass("Humanoid")

				if character then
					character.PlatformStand = false
				end
			end)

			slicedfn24()
			slicedfn36()
			slicedfn22(tbl15.Bad, 1.6)
		end
	end

	local slicedn5 = 25

	local function slicedfn41()
		if antiGuard.HitArms <= 0 then
			return false
		end

		if slicedn5 < os.clock() - (antiGuard.HitArmedAt or 0) then
			antiGuard.HitArms = 0
			return false
		end
		return true
	end

	local function slicedfn42()
		local carrying = tbl18.Carrying
		tbl18.Carrying = tbl18.SignalCarrying or tbl18.WeldCarrying
		local enabled = tbl18.Carrying and not carrying and flag4  and antiGuard.Enabled
		local flag5

		if enabled then
			flag5 = not (tbl4.SafeCarry.StopMode or tbl4.SafeCarry.Teleport)
		else
			flag5 = enabled
		end

		if flag5 and not tbl18.Active and not slicedfn41() then
			tbl18.Active = true
			antiGuard.Busy = true
			antiGuard.BusySince = os.clock()
			task.spawn(slicedfn40, os.clock())
		end
	end

	-- lets the delivery start the guard run again at every stop on the way home
	antiGuard.Fire = function()
		if flag4 and antiGuard.Enabled and not tbl4.SafeCarry.Teleport and not tbl18.Active and not slicedfn41() then
			tbl18.Active = true
			antiGuard.Busy = true
			antiGuard.BusySince = os.clock()
			task.spawn(slicedfn40, os.clock())
			return true
		end
		return false
	end

	local eggState = tbl.EggState
	local carryChanged = type(eggState) == "table" and eggState.CarryChanged or nil

	if type(carryChanged) == "table" and type(carryChanged.Connect) == "function" then
		local ok, result = pcall(carryChanged.Connect, carryChanged, function(arg)
			local signalCarrying = type(arg) == "table" and arg.IsCarrying == true

			if signalCarrying and arg.GuardDisabled == true then
				signalCarrying = false
			end

			if signalCarrying and type(arg.AreaId) == "string" then
				tbl18.AreaId = arg.AreaId
			end

			if not signalCarrying then
				tbl18.AreaId = nil
			end

			tbl18.SignalCarrying = signalCarrying
			slicedfn42()
		end)

		if ok and result then
			tbl17[#tbl17 + 1] = result
		end
	end

	local slicedn6 = 0

	tbl17[#tbl17 + 1] = RunService.Heartbeat:Connect(function(deltaTime)
		local busy = antiGuard.Busy or tbl18.Active
		local flag5

		if busy then
			local busySince = antiGuard.BusySince
			flag5 = os.clock() - busySince > math.max(tonumber(slicedfn32().BusyLimit) or tbl14.BusyLimit, (tonumber(slicedfn32().ReleaseAt) or 0) + 1)
		else
			flag5 = busy
		end

		if flag5 then
			slicedfn24()
			local humanoid = localPlayer.Character and localPlayer.Character:FindFirstChildOfClass("Humanoid")

			if humanoid and humanoid.PlatformStand then
				pcall(function()
					humanoid.PlatformStand = false
				end)
			end

			slicedfn36()
		end

		slicedfn41()
		slicedn6 += deltaTime
		if slicedn6 < tbl14.WeldScanGap then
			return
		end
		slicedn6 = 0
		local weldCarrying = slicedfn23() ~= nil

		if weldCarrying ~= tbl18.WeldCarrying then
			tbl18.WeldCarrying = weldCarrying
			slicedfn42()
		end
	end)

	slicedfn4(function()
		flag4 = false

		for _, sliced10 in ipairs(tbl17) do
			pcall(function()
				sliced10:Disconnect()
			end)
		end

		table.clear(tbl17)
		slicedfn24()
		slicedfn36()
		antiGuard.Render = nil
		antiGuard.ShowPanel = nil

		pcall(function()
			ScreenGui:Destroy()
		end)
	end)
end

v:Finalize({ Window = sliced2, MainTab = defaultTab, ShowMainTab = true })

task.defer(function()
	for i = 1, 3 do
		RunService.Heartbeat:Wait()
	end

	if type(tbl4.RestoreStealPanel) == "function" then
		pcall(tbl4.RestoreStealPanel)
	end
end)

