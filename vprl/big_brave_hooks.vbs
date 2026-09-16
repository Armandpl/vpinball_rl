' RL adapter for JPSalas's Big Brave 6.0.1. Original rules remain unchanged.
Dim RLStarted, RLLeft, RLRight, RLLaunchTicks
RLStarted = False: RLLeft = 0: RLRight = 0: RLLaunchTicks = 0

Sub RLReset
    ' The pool initializes each fresh process once; no old EM timers survive.
    bFreePlay = True
    EnteringInitials = False
    ResetScores
    ResetForNewGame
    RLStarted = True
End Sub

Sub RLApplyAction(l, r)
    If Not bGameInPlay Then Exit Sub
    If l <> RLLeft Then
        If l = 1 Then Table1_KeyDown LeftFlipperKey Else Table1_KeyUp LeftFlipperKey
    End If
    If r <> RLRight Then
        If r = 1 Then Table1_KeyDown RightFlipperKey Else Table1_KeyUp RightFlipperKey
    End If
    RLLeft = l: RLRight = r
End Sub

Sub RLTick
    If Not RLStarted Then RLReset
    If Not bGameInPlay Then Exit Sub
    ' v601 retains swPlungerRest handlers but has no such trigger object.
    ' Detect a settled ball in the physical shooter lane instead.
    bBallInPlungerLane = RLInShooterLane
    If RLLaunchTicks = 0 And bBallInPlungerLane Then
        Table1_KeyDown PlungerKey
        RLLaunchTicks = 1500
    End If
    If RLLaunchTicks > 0 Then
        RLLaunchTicks = RLLaunchTicks - 1
        If RLLaunchTicks = 500 Then Table1_KeyUp PlungerKey
    End If
End Sub

Function RLInShooterLane
    Dim ball
    RLInShooterLane = False
    For Each ball In GetBalls
        If Abs(ball.X - Plunger.X) < 30 And ball.Y > Plunger.Y - 200 Then
            If Abs(ball.VelY) < 1 Then RLInShooterLane = True
        End If
    Next
End Function

Function RLObserve
    Dim points
    points = 0
    If RLStarted Then points = Score(1)
    RLObserve = "{""score"":" & CStr(points) & ",""game_over"":" & LCase(CStr(RLStarted And Not bGameInPlay)) & "}"
End Function
