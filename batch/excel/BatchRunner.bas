Attribute VB_Name = "BatchRunner"
' AASHTO batch runner - Excel side.
' Run button -> RunBatch: writes the Inputs / Settings sheets to UTF-8 TSV files next to the
' workbook, runs AASHTO_Batch.exe on them (hidden), then imports _batch_results.tsv into Results.
' Columns are found by their header text, never by position, so columns can be reordered.
' Numbers are exported with Str (always "." decimal) and imported with Val, so the workbook works
' with any Windows decimal separator. Keep this file ASCII: the VBA editor imports .bas as ANSI.
Option Explicit

#If VBA7 Then
Private Declare PtrSafe Sub Sleep Lib "kernel32" (ByVal ms As Long)
#Else
Private Declare Sub Sleep Lib "kernel32" (ByVal ms As Long)
#End If

' Sheet layout - must match batch/columns.py (pinned by tests/test_batch_vba_static.py)
Private Const INPUT_HEADER_ROW As Long = 2
Private Const INPUT_FIRST_DATA_ROW As Long = 4
Private Const SETTINGS_FIRST_ROW As Long = 2
Private Const RESULTS_HEADER_ROW As Long = 2
Private Const RESULTS_FIRST_DATA_ROW As Long = 4

Private Const SH_INPUTS As String = "Inputs"
Private Const SH_SETTINGS As String = "Settings"
Private Const SH_RESULTS As String = "Results"
Private Const EXE_NAME As String = "AASHTO_Batch.exe"
Private Const POLL_MS As Long = 300

Public Sub RunBatch()
    Dim folder As String, exe As String, cmd As String, procName As String
    Dim summaryPath As String, progressPath As String, resultsPath As String
    Dim sh As Object, t0 As Single, gone As Long, txt As String

    folder = ThisWorkbook.Path
    If folder = "" Then
        MsgBox "Save the workbook first - the exchange files are written next to it.", vbExclamation
        Exit Sub
    End If
    If LCase$(Left$(folder, 4)) = "http" Then
        MsgBox "The workbook is open from a OneDrive / SharePoint web location (" & folder & ")." & vbLf & _
               "Save a copy to a local or synced folder and run from there.", vbExclamation
        Exit Sub
    End If

    exe = Trim$(SettingValue("Engine exe"))
    If exe = "" Then exe = folder & "\" & EXE_NAME
    If Not FileExists(exe) Then
        MsgBox "Engine not found:" & vbLf & exe & vbLf & vbLf & _
               "Put " & EXE_NAME & " next to the workbook, or set 'Engine exe' on the Settings sheet.", vbExclamation
        Exit Sub
    End If
    procName = Mid$(exe, InStrRev(exe, "\") + 1)

    summaryPath = folder & "\_batch_summary.txt"
    progressPath = folder & "\_batch_progress.txt"
    resultsPath = folder & "\_batch_results.tsv"
    KillIfExists summaryPath
    KillIfExists progressPath
    KillIfExists resultsPath

    On Error GoTo Fail
    WriteUtf8 folder & "\_batch_inputs.tsv", SheetToTsv(ThisWorkbook.Worksheets(SH_INPUTS), INPUT_HEADER_ROW, INPUT_FIRST_DATA_ROW, 0)
    WriteUtf8 folder & "\_batch_settings.tsv", SheetToTsv(ThisWorkbook.Worksheets(SH_SETTINGS), SETTINGS_FIRST_ROW - 1, SETTINGS_FIRST_ROW, 2)

    cmd = Chr(34) & exe & Chr(34) & " --dir " & Chr(34) & folder & Chr(34) & _
          " --workbook " & Chr(34) & ThisWorkbook.FullName & Chr(34)
    Set sh = CreateObject("WScript.Shell")
    Application.StatusBar = "AASHTO batch: starting engine..."
    sh.Run cmd, 0, False

    ' Poll: done when the summary file appears; failed if the engine process vanished without one.
    t0 = Timer
    Do
        DoEvents
        Sleep POLL_MS
        If FileExists(summaryPath) Then Exit Do
        If FileExists(progressPath) Then
            txt = ReadUtf8(progressPath)
            If txt <> "" Then Application.StatusBar = "AASHTO batch: section " & Replace(Replace(txt, vbCr, ""), vbLf, " ")
        End If
        If Abs(Timer - t0) > 3 Then
            If ProcessCount(procName) = 0 Then gone = gone + 1 Else gone = 0
            If gone >= 3 And Not FileExists(summaryPath) Then
                Application.StatusBar = False
                MsgBox "The engine stopped without writing a summary." & vbLf & "Command: " & cmd, vbCritical
                Exit Sub
            End If
        End If
    Loop
    Sleep POLL_MS  ' let the engine finish closing the summary file
    Application.StatusBar = False
    ShowSummary ReadSummary(summaryPath), resultsPath
    Exit Sub
Fail:
    Application.StatusBar = False
    MsgBox "Batch run failed: " & Err.Description, vbCritical
End Sub

Private Sub ShowSummary(ByVal s As Object, ByVal resultsPath As String)
    Dim msg As String
    If s("status") <> "done" Then
        MsgBox "The engine could not run:" & vbLf & s("message"), vbCritical
        Exit Sub
    End If
    If FileExists(resultsPath) Then ImportResults resultsPath
    msg = "Sections: " & s("sections") & vbLf & "Rows: " & s("rows") & vbLf & "Rows with errors: " & s("errors")
    If s("project") <> "" Then msg = msg & vbLf & vbLf & "Project file:" & vbLf & s("project")
    If s("project_error") <> "" Then msg = msg & vbLf & vbLf & s("project_error")
    MsgBox msg, IIf(s("errors") = "0" And s("project_error") = "", vbInformation, vbExclamation), "AASHTO batch"
    ThisWorkbook.Worksheets(SH_RESULTS).Activate
End Sub

' ---- export -----------------------------------------------------------------------------------

' Header row + data rows (firstRow..last used row) as TSV. maxCols = 0: up to the last header.
Private Function SheetToTsv(ByVal ws As Worksheet, ByVal headerRow As Long, ByVal firstRow As Long, _
                            ByVal maxCols As Long) As String
    Dim nCols As Long, lastRow As Long, r As Long, c As Long, v As Variant, out As String, rowTxt As String

    nCols = ws.Cells(headerRow, ws.Columns.Count).End(xlToLeft).Column
    If maxCols > 0 And nCols > maxCols Then nCols = maxCols
    lastRow = LastUsedRow(ws, nCols)
    If lastRow < firstRow Then lastRow = firstRow - 1

    out = RowToTsv(ws.Range(ws.Cells(headerRow, 1), ws.Cells(headerRow, nCols)).Value, nCols) & vbCrLf
    If lastRow >= firstRow Then
        v = ws.Range(ws.Cells(firstRow, 1), ws.Cells(lastRow, nCols)).Value
        For r = 1 To lastRow - firstRow + 1
            rowTxt = ""
            For c = 1 To nCols
                If c > 1 Then rowTxt = rowTxt & vbTab
                rowTxt = rowTxt & CellText(v(r, c))
            Next c
            out = out & rowTxt & vbCrLf
        Next r
    End If
    SheetToTsv = out
End Function

Private Function RowToTsv(ByVal v As Variant, ByVal nCols As Long) As String
    Dim c As Long, rowTxt As String
    If Not IsArray(v) Then RowToTsv = CellText(v): Exit Function
    For c = 1 To nCols
        If c > 1 Then rowTxt = rowTxt & vbTab
        rowTxt = rowTxt & CellText(v(1, c))
    Next c
    RowToTsv = rowTxt
End Function

' Locale-independent cell text: numbers via Str ("." decimal), booleans as TRUE / FALSE.
Private Function CellText(ByVal v As Variant) As String
    Select Case VarType(v)
        Case vbEmpty, vbNull, vbError
            CellText = ""
        Case vbBoolean
            CellText = IIf(v, "TRUE", "FALSE")
        Case vbDouble, vbSingle, vbInteger, vbLong, vbCurrency, vbDecimal, vbByte
            CellText = Trim$(Str$(v))
        Case Else
            CellText = Trim$(Replace(Replace(Replace(v & "", vbTab, " "), vbCr, " "), vbLf, " "))
    End Select
End Function

Private Function LastUsedRow(ByVal ws As Worksheet, ByVal nCols As Long) As Long
    Dim c As Long, r As Long, best As Long
    For c = 1 To nCols
        r = ws.Cells(ws.Rows.Count, c).End(xlUp).Row
        If r > best Then best = r
    Next c
    LastUsedRow = best
End Function

Private Function SettingValue(ByVal label As String) As String
    Dim ws As Worksheet, r As Long, lastRow As Long
    Set ws = ThisWorkbook.Worksheets(SH_SETTINGS)
    lastRow = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row
    For r = SETTINGS_FIRST_ROW To lastRow
        If LCase$(Trim$(ws.Cells(r, 1).Value & "")) = LCase$(label) Then
            SettingValue = CellText(ws.Cells(r, 2).Value)
            Exit Function
        End If
    Next r
End Function

' ---- import -----------------------------------------------------------------------------------

' Results TSV: header line, units line, one line per input data row (same order as Inputs).
Public Sub ImportResults(ByVal path As String)
    Dim ws As Worksheet, lines() As String, hdr() As String, f() As String
    Dim colOf() As Long, nTsv As Long, nRows As Long, maxCol As Long, lastRow As Long
    Dim i As Long, j As Long, k As Long, data() As Variant, s As String, statusCol As Long, isText() As Boolean

    Set ws = ThisWorkbook.Worksheets(SH_RESULTS)
    s = Replace(ReadUtf8(path), vbCrLf, vbLf)
    Do While Right$(s, 1) = vbLf
        s = Left$(s, Len(s) - 1)
    Loop
    lines = Split(s, vbLf)
    If UBound(lines) < 1 Then Exit Sub
    hdr = Split(lines(0), vbTab)
    nTsv = UBound(hdr) + 1

    ' Map every TSV column to a Results column by header text; unknown headers are appended.
    ReDim colOf(0 To nTsv - 1)
    maxCol = ws.Cells(RESULTS_HEADER_ROW, ws.Columns.Count).End(xlToLeft).Column
    If maxCol = 1 And Trim$(ws.Cells(RESULTS_HEADER_ROW, 1).Value & "") = "" Then maxCol = 0
    For j = 0 To nTsv - 1
        colOf(j) = 0
        For k = 1 To maxCol
            If LCase$(Trim$(ws.Cells(RESULTS_HEADER_ROW, k).Value & "")) = LCase$(Trim$(hdr(j))) Then colOf(j) = k: Exit For
        Next k
        If colOf(j) = 0 Then
            maxCol = maxCol + 1
            colOf(j) = maxCol
            ws.Cells(RESULTS_HEADER_ROW, maxCol).Value = hdr(j)
        End If
        If LCase$(Trim$(hdr(j))) = "status" Then statusCol = colOf(j)
    Next j

    ' Clear the units row and the old data area.
    lastRow = LastUsedRow(ws, maxCol)
    If lastRow >= RESULTS_HEADER_ROW + 1 Then
        ws.Range(ws.Cells(RESULTS_HEADER_ROW + 1, 1), ws.Cells(lastRow, maxCol)).ClearContents
        ws.Range(ws.Cells(RESULTS_HEADER_ROW + 1, 1), ws.Cells(lastRow, maxCol)).Interior.ColorIndex = xlColorIndexNone
    End If

    ' Units line -> the row under the headers; data lines -> from RESULTS_FIRST_DATA_ROW.
    f = Split(lines(1), vbTab)
    For j = 0 To nTsv - 1
        If j <= UBound(f) Then ws.Cells(RESULTS_HEADER_ROW + 1, colOf(j)).Value = f(j)
    Next j
    nRows = UBound(lines) - 1
    If nRows < 1 Then Exit Sub
    ' Text columns (Section ID, Status, Message...) are formatted "@" by the template builder: keep their
    ' values as text so an ID like "1-2" or "001" is not turned into a number or a date.
    ReDim isText(0 To nTsv - 1)
    For j = 0 To nTsv - 1
        isText(j) = (ws.Cells(RESULTS_FIRST_DATA_ROW, colOf(j)).NumberFormat = "@")
    Next j
    ReDim data(1 To nRows, 1 To maxCol)
    For i = 1 To nRows
        f = Split(lines(i + 1), vbTab)
        For j = 0 To nTsv - 1
            If j <= UBound(f) Then
                If isText(j) Or Not IsNumberText(f(j)) Then data(i, colOf(j)) = f(j) Else data(i, colOf(j)) = Val(UCase$(f(j)))
            End If
        Next j
    Next i
    ws.Range(ws.Cells(RESULTS_FIRST_DATA_ROW, 1), ws.Cells(RESULTS_FIRST_DATA_ROW + nRows - 1, maxCol)).Value = data

    If statusCol > 0 Then
        For i = 1 To nRows
            With ws.Cells(RESULTS_FIRST_DATA_ROW + i - 1, statusCol)
                Select Case UCase$(.Value & "")
                    Case "OK": .Interior.Color = RGB(198, 239, 206)
                    Case "NG": .Interior.Color = RGB(255, 199, 206)
                    Case "ERROR": .Interior.Color = RGB(255, 235, 156)
                End Select
            End With
        Next i
    End If
End Sub

' True only for a plain number: [sign] mantissa [e|E [sign] digits], mantissa = digits[.digits] or .digits.
' "inf", "nan", "1-2", "3e", "--1" and any other text -> False.
Private Function IsNumberText(ByVal s As String) As Boolean
    Dim i As Long, n As Long, ch As String, state As String, mant As Long, expo As Long
    s = Trim$(s)
    n = Len(s)
    If n = 0 Then Exit Function
    state = "sign"
    For i = 1 To n
        ch = Mid$(s, i, 1)
        Select Case state
            Case "sign"   ' optional leading sign, then the mantissa
                If ch = "+" Or ch = "-" Then
                    state = "mant"
                ElseIf ch Like "#" Then
                    mant = mant + 1: state = "mant"
                ElseIf ch = "." Then
                    state = "frac"
                Else
                    Exit Function
                End If
            Case "mant"   ' integer digits
                If ch Like "#" Then
                    mant = mant + 1
                ElseIf ch = "." Then
                    state = "frac"
                ElseIf (ch = "e" Or ch = "E") And mant > 0 Then
                    state = "esign"
                Else
                    Exit Function
                End If
            Case "frac"   ' fraction digits
                If ch Like "#" Then
                    mant = mant + 1
                ElseIf (ch = "e" Or ch = "E") And mant > 0 Then
                    state = "esign"
                Else
                    Exit Function
                End If
            Case "esign"  ' optional exponent sign
                If ch = "+" Or ch = "-" Then
                    state = "expo"
                ElseIf ch Like "#" Then
                    expo = expo + 1: state = "expo"
                Else
                    Exit Function
                End If
            Case "expo"   ' exponent digits
                If ch Like "#" Then expo = expo + 1 Else Exit Function
        End Select
    Next i
    If mant = 0 Then Exit Function
    If state = "esign" Or (state = "expo" And expo = 0) Then Exit Function
    IsNumberText = True
End Function

Private Function ReadSummary(ByVal path As String) As Object
    Dim d As Object, ln As Variant, p As Long, key As Variant
    Set d = CreateObject("Scripting.Dictionary")
    For Each key In Array("status", "sections", "rows", "errors", "project", "project_error", "message")
        d(key) = ""
    Next key
    For Each ln In Split(Replace(ReadUtf8(path), vbCr, ""), vbLf)
        p = InStr(1, ln, "=")
        If p > 1 Then d(Left$(ln, p - 1)) = Mid$(ln, p + 1)
    Next ln
    Set ReadSummary = d
End Function

' ---- files / processes ------------------------------------------------------------------------

Private Sub WriteUtf8(ByVal path As String, ByVal content As String)
    Dim st As Object
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.WriteText content
    st.SaveToFile path, 2
    st.Close
End Sub

Private Function ReadUtf8(ByVal path As String) As String
    Dim st As Object
    On Error GoTo Done
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.LoadFromFile path
    ReadUtf8 = st.ReadText
    st.Close
Done:
End Function

' Scripting.FileSystemObject is Unicode-safe; Dir / Kill go through the ANSI code page and miss
' paths with characters outside it.
Private Function FileExists(ByVal path As String) As Boolean
    FileExists = CreateObject("Scripting.FileSystemObject").FileExists(path)
End Function

Private Sub KillIfExists(ByVal path As String)
    Dim fso As Object
    Set fso = CreateObject("Scripting.FileSystemObject")
    If fso.FileExists(path) Then fso.DeleteFile path, True
End Sub

Private Function ProcessCount(ByVal exeName As String) As Long
    On Error GoTo Unknown
    ProcessCount = GetObject("winmgmts:\\.\root\cimv2").ExecQuery( _
        "SELECT ProcessId FROM Win32_Process WHERE Name='" & Replace(exeName, "'", "''") & "'").Count
    Exit Function
Unknown:
    ProcessCount = 1  ' cannot tell - assume still running; the summary file ends the wait
End Function
