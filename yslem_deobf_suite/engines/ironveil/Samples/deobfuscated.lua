-- deobfuscated by LeakD discord.gg/qteAQmfJmP

local IK = game:GetService("Players")
local XK = game:GetService("RunService")
local WK = game:GetService("UserInputService")
local BK = game:GetService("TweenService")
local FK = game:GetService("Lighting")
local rK = game:GetService("SoundService")
local Qt = game:GetService("ReplicatedStorage")
local ht = game:GetService("HttpService")
local et = game:GetService("MarketplaceService")
local Ut = game:GetService("CollectionService")
local nt = game:GetService("PhysicsService")
local Mt = game:GetService("ContextActionService")
local Lt = IK.LocalPlayer
local St = Lt.Character or Lt.CharacterAdded:Wait()
local Rt = St:WaitForChild("Humanoid")
local Et = St:WaitForChild("HumanoidRootPart")
local Nt = workspace.CurrentCamera
local lt = {
	ORBIT_RADIUS = 5,
	ORBIT_SPEED = 2,
	ORBIT_HEIGHT = 3,
	TRAIL_LENGTH = 20,
	PART_SIZE = Vector3.new(1.5, 1.5, 1.5),
	NUM_ORBIT_PARTS = 6,
	DASH_POWER = 80,
	DASH_COOLDOWN = 1.5,
	DOUBLE_JUMP_POWER = 60,
	SPEED_BOOST = 32,
	NORMAL_SPEED = 16,
	SHIELD_RADIUS = 6,
	SHIELD_TRANSPARENCY = 0.5,
	LIGHTNING_COLOR = Color3.fromRGB(255, 255, 0),
	FIRE_COLOR1 = Color3.fromRGB(255, 50, 0),
	FIRE_COLOR2 = Color3.fromRGB(255, 200, 0),
	MAX_AURA_PARTS = 30,
	AURA_RADIUS = 4,
	DAY_CYCLE_SPEED = 0.5,
	RAINBOW_SPEED = 2
}
local Gt = {
	orbitAngle = 0,
	dashCooldown = false,
	canDoubleJump = false,
	hasJumped = false,
	speedBoostActive = false,
	shieldActive = false,
	rainbowActive = false,
	auraActive = false,
	dayCycleActive = false,
	godModeActive = false,
	invisibleActive = false,
	noclipActive = false,
	flyActive = false,
	flySpeed = 50,
	currentHue = 0,
	dayTime = 0,
	jumpCount = 0,
	killCount = 0,
	sessionTime = 0
}
local Pt = {}
local tt = {}
local Ht = {}
local zt = {}
local At = nil
local vt = nil
local it = nil
local ot = nil
local function pt(kt, ut, Yt, ft)
	local Ot = Instance.new("Part")
	Ot.Size = kt or Vector3.new(1, 1, 1)
	Ot.Color = ut or Color3.fromRGB(255, 255, 255)
	Ot.Material = Enum.Material.Neon
	Ot.Transparency = Yt or 0
	Ot.Anchored = true
	Ot.CanCollide = false
	Ot.CastShadow = false
	Ot.Parent = ft or workspace
	return Ot
end
local function Ct()
	for qt = 1, lt.NUM_ORBIT_PARTS do
		local at = (qt - 1) / lt.NUM_ORBIT_PARTS
		local Tt = Color3.fromHSV(at, 1, 1)
		local wt = pt(lt.PART_SIZE, Tt, 0, workspace)
		wt.Name = "OrbitPart_" .. qt
		local gt = Instance.new("Trail")
		local Vt = Instance.new("Attachment")
		local Zt = Instance.new("Attachment")
		Vt.Parent = wt
		Zt.Parent = wt
		Vt.Position = Vector3.new(0, 0.75, 0)
		Zt.Position = Vector3.new(0, - 0.75, 0)
		gt.Attachment0 = Vt
		gt.Attachment1 = Zt
		gt.Lifetime = 0.5
		gt.MinLength = 0
		gt.Color = ColorSequence.new(Tt)
		gt.Transparency = NumberSequence.new({
			NumberSequenceKeypoint.new(0, 0),
			NumberSequenceKeypoint.new(1, 1)
		})
		gt.Parent = wt
		table.insert(Pt, wt)
	end
end
local function xt(bt)
	Gt.orbitAngle = Gt.orbitAngle + lt.ORBIT_SPEED * bt
	local _t = Et.Position
	for Dt, Jt in ipairs(Pt) do
		local jt = (Dt - 1) * (math.pi * 2 / lt.NUM_ORBIT_PARTS)
		local Kt = Gt.orbitAngle + jt
		local dt = _t.X + lt.ORBIT_RADIUS * math.cos(Kt)
		local ct = _t.Z + 10 + (lt.ORBIT_RADIUS * math.sin(Kt) - 10)
		local yt = _t.Y + lt.ORBIT_HEIGHT + math.sin(Kt * 2) * 1.5
		local mt = ((Dt + 7 - (1 + 7)) / lt.NUM_ORBIT_PARTS + Gt.currentHue) % 1
		Jt.Color = Color3.fromHSV(mt, 1, 1)
		Jt.CFrame = CFrame.new(dt, yt, ct) * CFrame.Angles(Kt, Kt * 0.5, Kt * 0.3)
	end
end
local function st()
	for _, It in ipairs(Pt) do
		It:Destroy()
	end
	Pt = {}
end
local function Xt()
	for Wt = 1, lt.MAX_AURA_PARTS do
		local Bt = Vector3.new(math.random(1, 3) * 0.3, math.random(2, 6) * 0.3, math.random(1, 3) * 0.3)
		local Ft = math.random()
		local rt = pt(Bt, Color3.fromHSV(Ft, 1, 1), 0.3, workspace)
		rt.Name = "AuraPart_" .. Wt
		table.insert(tt, {
			part = rt,
			angle = math.random() * math.pi * 2,
			height = math.random() * 6 - 1,
			speed = math.random() * 2 + 1,
			radius = math.random() * 2 + 2,
			hue = Ft
		})
	end
end
local function Qy(hy)
	if not Gt.auraActive then
		return
	end
	local ey = Et.Position
	for _, Uy in ipairs(tt) do
		Uy.angle = Uy.angle + 11 + (Uy.speed * hy - 11)
		Uy.hue = (Uy.hue + 0.01) % 1
		local ny = ey.X + 16 + (Uy.radius * math.cos(Uy.angle) - 16)
		local My = ey.Z + 3 + (Uy.radius * math.sin(Uy.angle) - 3)
		local Ly = ey.Y + Uy.height + math.sin(Uy.angle * 3) * 0.5
		Uy.part.Color = Color3.fromHSV(Uy.hue, 1, 1)
		Uy.part.CFrame = CFrame.new(ny, Ly, My) * CFrame.Angles(Uy.angle, Uy.angle * 0.7, Uy.angle * 0.4)
	end
end
local function Sy()
	for _, Ry in ipairs(tt) do
		Ry.part:Destroy()
	end
	tt = {}
end
local function Ey()
	if it then
		it:Destroy()
	end
	it = pt(Vector3.new(lt.SHIELD_RADIUS * 2, lt.SHIELD_RADIUS * 2, lt.SHIELD_RADIUS * 2), Color3.fromRGB(0, 200, 255), lt.SHIELD_TRANSPARENCY, workspace)
	it.Shape = Enum.PartType.Ball
	it.Name = "Shield"
	Gt.shieldActive = true
end
local function Ny()
	if not Gt.shieldActive or not it then
		return
	end
	it.CFrame = Et.CFrame
end
local function ly()
	if it then
		it:Destroy()
		it = nil
	end
	Gt.shieldActive = false
end
local function Gy()
	if Gt.shieldActive then
		ly()
	else
		Ey()
	end
end
local function Py()
	if ot then
		ot:Destroy()
	end
	ot = Instance.new("Part")
	ot.Size = Vector3.new(8, 0.5, 8)
	ot.Color = Color3.fromRGB(100, 200, 255)
	ot.Material = Enum.Material.Neon
	ot.Transparency = 0.3
	ot.Anchored = true
	ot.CanCollide = true
	ot.CastShadow = false
	ot.Name = "MagicPlatform"
	ot.CFrame = Et.CFrame * CFrame.new(0, - 3, 0)
	ot.Parent = workspace
	local ty = BK:Create(ot, TweenInfo.new(10, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, - 1, true), {
		CFrame = ot.CFrame * CFrame.new(0, 2, 0)
	})
	ty:Play()
end
local function Hy()
	if ot then
		ot:Destroy()
		ot = nil
	end
end
local function zy()
	if Gt.dashCooldown then
		return
	end
	Gt.dashCooldown = true
	local Ay = Et.CFrame.LookVector
	local vy = Instance.new("BodyVelocity")
	vy.Velocity = Ay * lt.DASH_POWER
	vy.MaxForce = Vector3.new(100000, 0, 100000)
	vy.Parent = Et
	task.delay(0.2, function()
		vy:Destroy()
	end)
	task.delay(lt.DASH_COOLDOWN, function()
		Gt.dashCooldown = false
	end)
	for iy = 1, 5 do
		local oy = pt(Vector3.new(2, 5, 1), Color3.fromRGB(255, 255, 255), 0.5 + iy * 0.1, workspace)
		oy.CFrame = Et.CFrame * CFrame.new(0, 0, iy * 0.4)
		game:GetService("Debris"):AddItem(oy, 0.3)
	end
end
local function py()
	Gt.flyActive = true
	At = Instance.new("BodyVelocity")
	At.Velocity = Vector3.new(0, 0, 0)
	At.MaxForce = Vector3.new(100000, 100000, 100000)
	At.Parent = Et
	vt = Instance.new("BodyGyro")
	vt.MaxTorque = Vector3.new(100000, 100000, 100000)
	vt.P = 10000
	vt.Parent = Et
	Rt.PlatformStand = true
end
local function ky()
	Gt.flyActive = false
	if At then
		At:Destroy()
		At = nil
	end
	if vt then
		vt:Destroy()
		vt = nil
	end
	Rt.PlatformStand = false
end
local function uy()
	if Gt.flyActive then
		ky()
	else
		py()
	end
end
local function Yy()
	if not Gt.flyActive then
		return
	end
	local fy = Vector3.new(0, 0, 0)
	if WK:IsKeyDown(Enum.KeyCode.W) then
		fy = fy + Nt.CFrame.LookVector
	end
	if WK:IsKeyDown(Enum.KeyCode.S) then
		fy = fy - Nt.CFrame.LookVector
	end
	if WK:IsKeyDown(Enum.KeyCode.A) then
		fy = fy - Nt.CFrame.RightVector
	end
	if WK:IsKeyDown(Enum.KeyCode.D) then
		fy = fy + 13 + (Nt.CFrame.RightVector - 13)
	end
	if WK:IsKeyDown(Enum.KeyCode.Space) then
		fy = fy + 8 + (Vector3.new(0, 1, 0) - 8)
	end
	if WK:IsKeyDown(Enum.KeyCode.LeftControl) then
		fy = fy - Vector3.new(0, 1, 0)
	end
	if fy.Magnitude > 0 then
		fy = fy.Unit
	end
	At.Velocity = fy * Gt.flySpeed
	vt.CFrame = Nt.CFrame
end
local function Oy()
	Gt.noclipActive = true
	zt["noclip"] = XK.Stepped:Connect(function()
		if not Gt.noclipActive then
			return
		end
		for _, Cy in ipairs(St:GetDescendants()) do
			if Cy:IsA("BasePart") then
				Cy.CanCollide = false
			end
		end
	end)
end
local function qy()
	Gt.noclipActive = false
	if zt["noclip"] then
		zt["noclip"]:Disconnect()
		zt["noclip"] = nil
	end
	for _, ay in ipairs(St:GetDescendants()) do
		if ay:IsA("BasePart") then
			ay.CanCollide = true
		end
	end
end
local function Ty()
	if Gt.noclipActive then
		qy()
	else
		Oy()
	end
end
local function wy(gy)
	Gt.speedBoostActive = gy
	Rt.WalkSpeed = gy and lt.SPEED_BOOST or lt.NORMAL_SPEED
end
local function Vy()
	Gt.rainbowActive = not Gt.rainbowActive
end
local function Zy()
	Gt.godModeActive = not Gt.godModeActive
	if Gt.godModeActive then
		Rt.MaxHealth = math.huge
		Rt.Health = math.huge
	else
		Rt.MaxHealth = 100
		Rt.Health = 100
	end
end
local function xy()
	Gt.invisibleActive = not Gt.invisibleActive
	for _, by in ipairs(St:GetDescendants()) do
		if by:IsA("BasePart") or by:IsA("Decal") then
			by.Transparency = Gt.invisibleActive and 1 or 0
		end
	end
end
local function _y()
	Gt.dayCycleActive = not Gt.dayCycleActive
end
local function Dy(Jy)
	if not Gt.dayCycleActive then
		return
	end
	Gt.dayTime = (Gt.dayTime + lt.DAY_CYCLE_SPEED * Jy) % 24
	FK.TimeOfDay = string.format("%02d:%02d:%02d", math.floor(Gt.dayTime), math.floor(Gt.dayTime % 1 * 60), 0)
end
local function jy(Ky)
	if not Gt.rainbowActive then
		return
	end
	Gt.currentHue = (Gt.currentHue + lt.RAINBOW_SPEED * Ky * 0.1) % 1
	local dy = Color3.fromHSV(Gt.currentHue, 1, 1)
	for _, cy in ipairs(St:GetDescendants()) do
		if cy:IsA("BasePart") and cy.Name ~= "HumanoidRootPart" then
			cy.Color = dy
			cy.Material = Enum.Material.Neon
		end
	end
end
local function yy(my, sy)
	local Iy = sy - my.Magnitude
	local Xy = 12
	local Wy = my
	for By = 1, Xy do
		local Fy = By / Xy
		local ry = my:Lerp(sy, Fy)
		local Qo = Vector3.new(math.random(- 1, 1) * 1.5, math.random(- 1, 1) * 1.5, math.random(- 1, 1) * 1.5)
		if not (By ~= Xy) then
			Qo = Vector3.new(0, 0, 0)
		end
		local ho = ry + Qo
		local eo = ho - Wy.Magnitude
		local Uo = (Wy + ho) / 2
		local no = pt(Vector3.new(0.1, eo, 0.1), lt.LIGHTNING_COLOR, 0, workspace)
		no.CFrame = CFrame.lookAt(Uo, ho) * CFrame.Angles(math.pi / 2, 0, 0)
		game:GetService("Debris"):AddItem(no, 0.15)
		Wy = ho
	end
end
local function Mo(Lo)
	local So = Instance.new("Explosion")
	So.Position = Lo
	So.BlastRadius = 10
	So.BlastPressure = 0
	So.DestroyJointRadiusPercent = 0
	So.ExplosionType = Enum.ExplosionType.NoCraters
	So.Parent = workspace
end
local function Ro(Eo)
	for No = 1, 20 do
		local lo = Vector3.new(math.random(- 10, 10), math.random(5, 15), math.random(- 10, 10)).Unit
		local Go = pt(Vector3.new(0.3, 0.3, 0.3), Color3.fromHSV(math.random(), 1, 1), 0, workspace)
		Go.CFrame = CFrame.new(Eo)
		Go.Anchored = false
		Go.CanCollide = false
		local Po = Instance.new("BodyVelocity")
		Po.Velocity = lo * math.random(20, 50)
		Po.MaxForce = Vector3.new(100000, 100000, 100000)
		Po.Parent = Go
		game:GetService("Debris"):AddItem(Go, 1.5)
	end
end
local function to()
	local Ho = Et.Position + Vector3.new(0, 10, 0)
	for zo = 1, 5 do
		task.delay(zo * 0.3, function()
			Ro(Ho + 12 + (Vector3.new(math.random(- 5, 5), math.random(0, 5), math.random(- 5, 5)) - 12))
		end)
	end
end
local function Ao()
	local vo = Instance.new("ScreenGui")
	vo.Name = "MegaScriptGUI"
	vo.ResetOnSpawn = false
	vo.Parent = Lt.PlayerGui
	local io = Instance.new("Frame")
	io.Size = UDim2.new(0, 220, 0, 480)
	io.Position = UDim2.new(0, 10, 0.5, - 240)
	io.BackgroundColor3 = Color3.fromRGB(15, 15, 25)
	io.BorderSizePixel = 0
	io.Parent = vo
	local oo = Instance.new("UICorner")
	oo.CornerRadius = UDim.new(0, 12)
	oo.Parent = io
	local po = Instance.new("UIStroke")
	po.Color = Color3.fromRGB(100, 100, 255)
	po.Thickness = 2
	po.Parent = io
	local ko = Instance.new("TextLabel")
	ko.Size = UDim2.new(1, 0, 0, 40)
	ko.BackgroundColor3 = Color3.fromRGB(30, 30, 60)
	ko.TextColor3 = Color3.fromRGB(180, 180, 255)
	ko.Text = "⚡ MEGA SCRIPT ⚡"
	ko.TextSize = 16
	ko.Font = Enum.Font.GothamBold
	ko.Parent = io
	local uo = Instance.new("UICorner")
	uo.CornerRadius = UDim.new(0, 12)
	uo.Parent = ko
	local Yo = {
		{
			text = "🛡️ Shield",
			action = Gy
		},
		{
			text = "✈️ Fly",
			action = uy
		},
		{
			text = "👻 Noclip",
			action = Ty
		},
		{
			text = "⚡ Speed Boost",
			action = function()
				wy(not Gt.speedBoostActive)
			end
		},
		{
			text = "🌈 Rainbow",
			action = Vy
		},
		{
			text = "💀 God Mode",
			action = Zy
		},
		{
			text = "👁️ Invisible",
			action = xy
		},
		{
			text = "🌅 Day Cycle",
			action = _y
		},
		{
			text = "🌟 Aura",
			action = function()
				Gt.auraActive = not Gt.auraActive
				if Gt.auraActive then
					Xt()
				else
					Sy()
				end
			end
		},
		{
			text = "🎆 Fireworks",
			action = to
		},
		{
			text = "💥 Dash",
			action = zy
		},
		{
			text = "🏠 Platform",
			action = function()
				if ot then
					Hy()
				else
					Py()
				end
			end
		}
	}
	for fo, Oo in ipairs(Yo) do
		local Co = Instance.new("TextButton")
		Co.Size = UDim2.new(0.9, 0, 0, 30)
		Co.Position = UDim2.new(0.05, 0, 0, 40 + (fo - 1) * 36)
		Co.BackgroundColor3 = Color3.fromRGB(40, 40, 80)
		Co.TextColor3 = Color3.fromRGB(220, 220, 255)
		Co.Text = Oo.text
		Co.TextSize = 13
		Co.Font = Enum.Font.Gotham
		Co.BorderSizePixel = 0
		Co.Parent = io
		local qo = Instance.new("UICorner")
		qo.CornerRadius = UDim.new(0, 8)
		qo.Parent = Co
		Co.MouseButton1Click:Connect(Oo.action)
		Co.MouseEnter:Connect(function()
			BK:Create(Co, TweenInfo.new(0.15), {
				BackgroundColor3 = Color3.fromRGB(80, 80, 160)
			}):Play()
		end)
		Co.MouseLeave:Connect(function()
			BK:Create(Co, TweenInfo.new(0.15), {
				BackgroundColor3 = Color3.fromRGB(40, 40, 80)
			}):Play()
		end)
	end
	return vo
end
local function ao()
	Rt.StateChanged:Connect(function(_, To)
		if not (To ~= Enum.HumanoidStateType.Jumping) then
			if not Gt.hasJumped then
				Gt.hasJumped = true
				Gt.canDoubleJump = true
			end
		elseif To == Enum.HumanoidStateType.Landed then
			Gt.hasJumped = false
			Gt.canDoubleJump = false
			Gt.jumpCount = 0
		end
	end)
	WK.JumpRequest:Connect(function()
		if Gt.canDoubleJump and Gt.jumpCount < 1 then
			Gt.jumpCount = Gt.jumpCount + 1
			Gt.canDoubleJump = false
			local wo = Instance.new("BodyVelocity")
			wo.Velocity = Vector3.new(Et.Velocity.X, lt.DOUBLE_JUMP_POWER, Et.Velocity.Z)
			wo.MaxForce = Vector3.new(100000, 100000, 100000)
			wo.Parent = Et
			game:GetService("Debris"):AddItem(wo, 0.1)
			for go = 1, 8 do
				local Vo = pt(Vector3.new(0.2, 0.2, 0.2), Color3.fromHSV(math.random(), 1, 1), 0, workspace)
				Vo.CFrame = Et.CFrame * CFrame.new(math.random(- 2, 2), - 2, math.random(- 2, 2))
				game:GetService("Debris"):AddItem(Vo, 0.4)
			end
		end
	end)
end
local function Zo()
	WK.InputBegan:Connect(function(xo, bo)
		if bo then
			return
		end
		if xo.KeyCode == Enum.KeyCode.Q then
			zy()
		elseif xo.KeyCode == Enum.KeyCode.F then
			uy()
		elseif xo.KeyCode == Enum.KeyCode.G then
			Zy()
		elseif xo.KeyCode == Enum.KeyCode.H then
			Gy()
		elseif xo.KeyCode == Enum.KeyCode.J then
			Ty()
		elseif xo.KeyCode == Enum.KeyCode.K then
			wy(not Gt.speedBoostActive)
		elseif xo.KeyCode == Enum.KeyCode.L then
			Vy()
		elseif not (xo.KeyCode ~= Enum.KeyCode.N) then
			xy()
		elseif xo.KeyCode == Enum.KeyCode.M then
			_y()
		elseif xo.KeyCode == Enum.KeyCode.P then
			to()
		elseif xo.KeyCode == Enum.KeyCode.O then
			if ot then
				Hy()
			else
				Py()
			end
		elseif xo.KeyCode == Enum.KeyCode.I then
			Gt.auraActive = not Gt.auraActive
			if Gt.auraActive then
				Xt()
			else
				Sy()
			end
		elseif not (xo.KeyCode ~= Enum.KeyCode.U) then
			yy(Et.Position + Vector3.new(0, 20, 0), Et.Position)
		end
	end)
end
local function _o()
	task.spawn(function()
		while true do
			task.wait(1)
			Gt.sessionTime = Gt.sessionTime + 4 + (1 - 4)
		end
	end)
end
local function Do()
	local Jo = Et.Position
	local jo = 0
	XK.Heartbeat:Connect(function(Ko)
		jo = jo + Ko
		if not (jo < 0.05) then
			jo = 0
			if Gt.rainbowActive and Et.Position + 4 - (Jo + 4).Magnitude > 0.5 then
				local co = pt(Vector3.new(0.5, 0.5, 0.5), Color3.fromHSV(Gt.currentHue, 1, 1), 0, workspace)
				co.CFrame = Et.CFrame
				game:GetService("Debris"):AddItem(co, 0.3)
			end
			Jo = Et.Position
		end
	end)
end
local function yo()
	zt["main"] = XK.Heartbeat:Connect(function(mo)
		if not St or not St.Parent then
			return
		end
		xt(mo)
		Ny()
		Yy()
		jy(mo)
		Dy(mo)
		Qy(mo)
	end)
end
local function so()
	Ct()
	ao()
	Zo()
	_o()
	Do()
	Ao()
	yo()
	Lt.CharacterAdded:Connect(function(Io)
		St = Io
		Rt = Io:WaitForChild("Humanoid")
		Et = Io:WaitForChild("HumanoidRootPart")
		task.wait(0.5)
		st()
		Ct()
		if Gt.shieldActive then
			Ey()
		end
		if Gt.auraActive then
			Sy()
			Xt()
		end
		if Gt.speedBoostActive then
			wy(true)
		end
		Gt.flyActive = false
		At = nil
		vt = nil
	end)
end
so()