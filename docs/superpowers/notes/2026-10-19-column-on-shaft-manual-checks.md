# Manual GUI checklists (from the Task 10 and Task 11 implementer reports)

## Manual GUI checklist for the user (run.bat)
1. Before updating, open an existing project and note the Project Summary numbers. After updating, reopen it: the numbers
   should be identical, and the other 11 tabs should look and behave as before (including Show All Tabs and Ctrl+S).
2. On the Column on Shaft tab, paste `tests/fixtures_csi/colshaft_2bent.txt` and click Parse. Expect 5 cases, frames 101,
   102 and 201, and the amber envelope notice.
3. Paste `tests/fixtures_csi/no_units_row.txt` and click Parse. Expect the red "Units ASSUMED" notice.
4. Set up two bents:
   - B1: column 101, shaft 102, D 60, Ds 84, basis cantilever, L_eq 10 ft.
   - B2: column 201, D 54, Ds 78, a soil profile (welch_stiff_clay 20 ft with γ 125, su 2.5/3.0, ε50 0.005; then api_sand
     60 ft with γ 125, φ′ 36, k 90, submerged), embedded length 60 ft.

   Click Design. Expect both bents OK, with B1 col 13-#14 and B2 col 15-#11, matching `test_colshaft_engine` "2b".
5. Clear B1's L_eq and click Design. Expect the red validation message and no run.
6. Override the B1 column longitudinal to #5 n 6 and click Design. B1 should turn NG with "col long" in the Override
   column. Then click Clear override.
7. Save the project, reload it and check that the tab state is restored. Results are not saved, so click Design again.
   Load an old project: the tab should come back empty.
8. Click each result row. Check that the drill-down tables, checks with refs, warnings and charts look sensible.
9. Run the exe build (`build.bat` or the spec) and check that the tab works in the frozen exe, where colshaft.js is inlined
   from `_MEIPASS`.


## Manual GUI checklist for the user (run.bat)
1. Do the Task 10 checklist first (steps 1–9 of task-10-report.md), including the old project, Save/Load and the exe build.
2. Run the 2-bent example (B1 cantilever, B2 soil) and click Design. Then click a result row and check the drill-down:
   - the M-φ chart shows a rising curve with the dashed bilinear line and φy/Mp and φu circles;
   - for B2, the shaft M/V/y charts show two bounds (×0.5 bold red "governing", ×2 blue), with Df_eq dashed.
3. In "8. Printable report", type a project name and click Generate. Check the sections 1–10 for each bent, in order, and that
   the "Assumptions & open decisions" box lists envelope bounding, S6 and E13/E14/E17. Check that every seismic reference ends
   with "(unverified — see OPEN_VERIFICATION_ITEMS E)".
4. Click "Print report". In the print preview, check:
   - only the Column on Shaft report prints (no tab UI, and no main Report tab content);
   - each bent starts on a new page;
   - no table is cut at the right margin (the final-checks table should wrap);
   - the charts fit two per row.
   Try Letter and A4, portrait.
5. Go to the Report tab, generate the main section report and print it. It must print as before, without the Column on Shaft
   report.
6. Repeat steps 4 and 5 with "Show All Tabs" on.
7. Override the B1 shaft longitudinal, Design again, and Generate. The overrides line and the final cage source "Override"
   should appear.
8. Use a soft soil so that a bound is unstable. In the shaft charts it should be dashed grey with "unstable (excluded)", and
   it must not flatten the other curves.
9. Save the project and reload it: the report Project name is kept. The report itself needs Design again, because results are
   not saved.
