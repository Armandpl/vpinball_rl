' license:GPLv3+
' Additional rules for the saved stripped-table mod. Original controls, nudging,
' slingshots, sound and animations above are deliberately preserved.
Dim RLScore, RLStarted, RLGameOver, RLActiveTarget, RLLeft, RLRight
Dim RLLaunchTicks, RLLastHit(5), RLIndicators, RLIndex
RLScore = 0: RLStarted = False: RLGameOver = False: RLActiveTarget = 1
RLLeft = 0: RLRight = 0: RLLaunchTicks = 1001
For RLIndex = 1 To 5: RLLastHit(RLIndex) = -1000: Next
RLIndicators = Array(RLIndicator1, RLIndicator2, RLIndicator3, RLIndicator4, RLIndicator5)
RLUpdateLights
ScoreText.Text = "0"

Sub RLUpdateLights
    Dim i
    For i = 0 To 4
        If i + 1 = RLActiveTarget Then RLIndicators(i).State = 1 Else RLIndicators(i).State = 0
    Next
End Sub

Sub RLHitTarget(index)
    If Not RLStarted Or RLGameOver Then Exit Sub
    If GameTime - RLLastHit(index) < 100 Then Exit Sub
    RLLastHit(index) = GameTime
    If index = RLActiveTarget Then
        RLScore = RLScore + 100
        RLActiveTarget = (RLActiveTarget Mod 5) + 1
        RLUpdateLights
    Else
        RLScore = RLScore + 10
    End If
    ScoreText.Text = CStr(RLScore)
End Sub

Sub RLTarget1_Hit: RLHitTarget 1: End Sub
Sub RLTarget2_Hit: RLHitTarget 2: End Sub
Sub RLTarget3_Hit: RLHitTarget 3: End Sub
Sub RLTarget4_Hit: RLHitTarget 4: End Sub
Sub RLTarget5_Hit: RLHitTarget 5: End Sub

Sub RLApplyAction(l, r)
    If RLGameOver Then Exit Sub
    If l <> RLLeft Then
        If l = 1 Then Table1_KeyDown LeftFlipperKey Else Table1_KeyUp LeftFlipperKey
    End If
    If r <> RLRight Then
        If r = 1 Then Table1_KeyDown RightFlipperKey Else Table1_KeyUp RightFlipperKey
    End If
    RLLeft = l: RLRight = r
End Sub

Sub RLReset
    ' Engine has removed any old ball. Preserve the world and monotonic GameTime;
    ' reset only this simple game's episode state and serve one new ball.
    Dim i
    RLScore = 0: RLStarted = False: RLGameOver = False: RLActiveTarget = 1
    RLLeft = 0: RLRight = 0: RLLaunchTicks = 1001
    For i = 1 To 5: RLLastHit(i) = GameTime - 1000: Next
    Table1_KeyUp LeftFlipperKey
    Table1_KeyUp RightFlipperKey
    Plunger.Fire
    StopSound "plungerpull"
    EnableBallControl = False: ControlBallInPlay = False
    Set ControlActiveBall = Nothing
    BCup = 0: BCdown = 0: BCleft = 0: BCright = 0
    LeftSlingShot.TimerEnabled = False: RightSlingShot.TimerEnabled = False
    LStep = 0: RStep = 0
    LSling.Visible = True: LSling1.Visible = False: LSling2.Visible = False
    RSling.Visible = True: RSling1.Visible = False: RSling2.Visible = False
    sling1.rotx = 0: sling2.rotx = 0
    For Each i In GI: i.State = 1: Next
    For i = 0 To tnob
        rolling(i) = False
        StopSound "fx_ballrolling" & i
    Next
    RLUpdateLights
    ScoreText.Text = "0"
    BIP = 0
    Plunger_Init
End Sub

Sub RLTick
    ' Pull automatically on the first physics tick, then release after one second.
    If RLLaunchTicks = 1001 Then Table1_KeyDown PlungerKey
    If RLLaunchTicks > 0 Then
        RLLaunchTicks = RLLaunchTicks - 1
        If RLLaunchTicks = 0 Then Table1_KeyUp PlungerKey
    End If
End Sub

Function RLObserve
    Dim remaining
    remaining = 1
    If RLGameOver Then remaining = 0
    RLObserve = "{""score"":" & CStr(RLScore) & ",""game_over"":" & LCase(CStr(RLGameOver)) & ",""started"":" & LCase(CStr(RLStarted)) & ",""balls_left"":" & CStr(remaining) & ",""launch_pending"":" & LCase(CStr(RLLaunchTicks > 0)) & ",""active_target"":" & CStr(RLActiveTarget) & "}"
End Function
