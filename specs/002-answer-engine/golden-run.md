# Golden run: Answer Engine (002)

Run at 2026-10-14 21:40 against the published dataset with `uv run pytest -q -m hosted tests/answer/test_golden.py`. Latency is wall-clock for the whole pipeline; cost is model spend for that question. Model calls were served from the cache where an identical call had been made before; those show near-zero latency and $0, so latency and cost are real only for the new calls (set GOLDEN_FRESH=1 to measure all).

| Q | User | Expected | Actual | Detail | Key facts hit | Missed | Forbidden present | Sentences / conflicts | Latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| q01 | u01 | answer | answer |  | cavitation, 15%, 10 s, NPSH, 0.30 bar, PI-01, 8.3 | - | - | 8 / 0 | 0.1 s | $0.0000 |
| q02 | u01 | answer | answer |  | 0.38, 0.50 mm | - | - | 3 / 0 | 0.0 s | $0.0000 |
| q03 | u03 | answer | answer |  | 6,000 h or 6,000 running hours, 12 months, SynLube 46, 4,000 h or 4,000 running hours | - | - | 4 / 0 | 0.0 s | $0.0000 |
| q04 | u04 | answer | answer |  | 38 N-m, HCP350-240001, HCP350-241187, crack | 00041988, June 2026 or 2026-06 | - | 4 / 0 | 0.1 s | $0.0000 |
| q05 | u02 | answer | answer |  | HV-PROC-02, 50 V DC, TP1, 100 MOhm, P9.01, 210 A, notify the site or inform the site or tell the site, 24 hours, Vastra L2, High case or High priority | - | - | 26 / 0 | 0.1 s | $0.0000 |
| q06 | u03 | restricted | restricted | HV-PROC-07, missing cert-hv | HV-PROC-07 | - | - | 4 / 0 | 0.1 s | $0.0000 |
| q07 | u12 | abstain | abstain | no_permitted_source | - | - | - | 0 / 0 | 0.1 s | $0.0000 |
| q08 | u03 | answer | answer |  | 00041207, 00042388, 41-2207, 5.1, exhaust duct | - | - | 12 / 0 | 0.0 s | $0.0000 |
| q09 | u05 | answer | answer |  | SB-2025-014, EXV, 63-1180, rev 3, SOP-020, KT-WI-14, low suction pressure, leak test | - | - | 17 / 0 | 0.1 s | $0.0000 |
| q10 | u12 | answer | answer | ; work order without asset | 77-0419, 0.5 mm | - | - | 13 / 0 | 0.1 s | $0.0000 |
| p1 | u06 | restricted | restricted | SOP-020, missing cert-refrigerant; work order without asset | SOP-020 | - | - | 3 / 0 | 0.0 s | $0.0000 |
| p2 | u05 | answer | answer | ; work order without asset | - | - | - | 23 / 0 | 0.1 s | $0.0000 |
| p3 | u10 | restricted | restricted | HV-PROC-07, missing cert-hv | HV-PROC-07 | - | - | 3 / 0 | 0.0 s | $0.0000 |
| c1 | u04 | clarify | clarify | FRS-P-0012 / FRS-P-0031 | - | - | - | 0 / 0 | 0.0 s | $0.0000 |
| a1 | u01 | abstain | abstain | unknown_asset | - | - | - | 0 / 0 | 0.0 s | $0.0000 |
| n1 | u12 | abstain | abstain | not_visible | - | - | - | 0 / 0 | 0.0 s | $0.0000 |
| m1 | u03 | restricted | restricted | HV-PROC-07, missing cert-hv; work order without asset | HV-PROC-07 | - | - | 3 / 0 | 0.0 s | $0.0000 |
| t1 | u01 | clarify | clarify | What's the impeller-to-casing clearance spec on an HCP-200? | - | - | - | 0 / 0 | 0.0 s | $0.0000 |
| f1 | u01 | answer | answer | ; answering: What's the impeller-to-casing clearance spec on an HCP-200? | 0.38, 0.50 mm | - | - | 3 / 0 | 0.0 s | $0.0000 |
| f2 | u03 | restricted | restricted | HV-PROC-07, missing cert-hv; answering: What does E-31 mean on TAC-C-0143, and how do I reset it?; machine TAC-C-0143 | HV-PROC-07 | - | - | 3 / 0 | 0.0 s | $0.0000 |
| f3 | u04 | answer | answer | ; answering: What torque do I use on the casing bolts for FRS-P-0012 after a seal change?; machine FRS-P-0012 | 45 N-m | - | - | 5 / 1 | 0.0 s | $0.0000 |

Total model cost of this run: $0.0000.

## Restricted-content disclosure check

For every response, the whole response JSON was scanned for the markers of every restricted procedure the asking user cannot satisfy, and every cited passage was re-checked with `serving.can_see` for that user.

Disclosures found: **0**.

## Responses

<details><summary>q01: answer</summary>

- statement: P-07 is cavitation: the suction pressure is fluctuating above 15% for 10 s because NPSH available is too low, most commonly from a clogged strainer, a throttled suction valve, or high liquid temperature. (1 citations)
- step: 1. First, read the strainer differential pressure at PI-01/PI-02. (2 citations)
- step: 2. If the strainer dP is above 0.30 bar, clean the strainer (section 8.3) because the manual ties that threshold to P-07 on the HCP-500. (1 citations)
- step: 3. After cleaning, confirm the suction isolation valve is fully open (section 7.2). (1 citations)
- statement: If the strainer dP is not above 0.30 bar, the next thing to check is whether the suction isolation valve is fully open, because a partly closed valve can still cause cavitation on this machine. (2 citations)
- statement: For this HCP-500 manual, the P-07 first check is the revised one in Revision B, which applies to HCP-500 serials from HCP500-230001 and controller firmware 3.x. (2 citations)
- statement: A unit record for FRS-P-0033 in August 2026 showed P-07 clearing after the strainer was cleaned and the suction valve was opened fully; the recorded strainer dP was 0.42 bar and the case was 00043015. (1 citations)
- warning: Do not rely on a quick visual check of the suction valve, because the playbook says a partly closed valve can look fine from a distance and still keep P-07 coming back. (1 citations)
- notice possibly_stale: HCP-500 Maintenance Quick Reference may be out of date; a newer source you can see is used instead.

</details>

<details><summary>q02: answer</summary>

- statement: For an HCP-200 in standard design, the impeller-to-casing clearance spec is 0.38 to 0.50 mm diametral. (1 citations)
- statement: This value applies to the standard design; special designs use the order confirmation. (2 citations)
- statement: If the clearance exceeds the maximum in table 3.1, you must renew the wear rings, because increasing clearance reduces flow rate and efficiency. (2 citations)
- notice translated: Some sources are machine translations; the viewer shows the original text.

</details>

<details><summary>q03: answer</summary>

- statement: For a VRS-75 with Vastra SynLube 46, you change the oil every 6,000 running hours or 12 months, whichever comes first, and that longer interval is valid only with genuine Vastra SynLube 46. (2 citations)
- statement: For a VRS-75 with mineral compressor oil ISO VG 46, you change the oil every 4,000 running hours or 12 months, whichever comes first. (2 citations)
- warning: If your VRS-75 was delivered before April 2026, the controller is set to a 4,000-hour oil interval from the factory, so you must change it manually when Vastra SynLube 46 is used. (1 citations)
- statement: A unit history on FRS-C-0101 shows the older 4,000-hour oil-change interval in use in February 2025 and October 2025, and a July 2026 service record shows SynLube 46 oil changed again with the oil filter and air filter after 4,000 hours since the last change. (4 citations)
- notice superseded: Vastra VRS-75 Service Manual Rev B is superseded; a newer source you can see is used instead.
- notice possibly_stale: VRS Series Oil and Filter Quick Reference may be out of date; a newer source you can see is used instead.

</details>

<details><summary>q04: answer</summary>

- statement: For FRS-P-0031, use 38 N-m on the casing bolts, in a cross pattern in two passes, because serial HCP350-241187 is in the HCP-350 range from HCP350-240001 and later with the revised casing cover and gasket. (4 citations)
- warning: Do not use 45 N-m on this pump; the bulletin says that torque applies only to HCP-350 serials before HCP350-240001, and over-torquing the revised casing can crack the gasket seat. (6 citations)
- statement: If the casing joint was already closed after the seal change, inspect the maintenance record and the joint for leakage; if 45 N-m was used or the torque is unknown, isolate and drain the pump and re-tighten to 38 N-m, then recheck after 24 hours at operating temperature. (6 citations)
- statement: If the joint leaks at 38 N-m, the gasket or gasket seat is damaged; open the joint, inspect the seat with dye penetrant, and replace the gasket or casing cover as required because a cracked seat cannot be repaired. (4 citations)
- notice bulletin: Halden SB-2025-009 applies to this unit.
- notice bulletin: Halden SB-2025-018 applies to this unit.
- work order: {"asset_id": "FRS-P-0031", "fault_code": null, "summary": "FRS-P-0031 is in Halden SB-2025-009 scope; if the casing joint was torqued to 45 N-m or is leaking, it needs isolation, inspection, and possible casing cover/gasket replacement.", "required_certification": [], "parts": [{"part_number": "18-0356", "quantity": 1}], "campaign_code": null, "citations": ["p_56831c217e16f7d0f8aa12da", "p_e35d98a44e996383173e0193", "p_6ba270621506e02e89917314", "p_ev_821fbc5201a95213", "p_ev_996bd95db591f746", "p_ev_9369fc1ff1651f9d"]}

</details>

<details><summary>q05: answer</summary>

- statement: E-31 is VFD overcurrent: the drive saw output current above its peak current limit, and the reset is not possible from the control panel. (3 citations)
- warning: If you are not HV-certified, do not open the VFD cabinet or try to clear E-31 yourself; the DC bus can stay charged after isolation and the panel reset is disabled on purpose. (3 citations)
- step: 1. Read the alarm log and note the E-31 time, load, motor speed, discharge pressure, ambient temperature, and any other alarms in the 24 hours before it. (2 citations)
- step: 2. Check the asset history for earlier E-31 trips and resets on TAC-C-0143, and if this E-31 was reset on this unit in the last 24 hours, stop and go to section 7. (4 citations)
- step: 3. Ask the site whether there was a power event near the trip time, and record who you asked and what they said because a confirmed supply dip is the most common harmless cause. (2 citations)
- step: 4. Notify the site that TAC-C-0143 will be isolated, normally for 60 to 90 minutes, and agree when it can go down. (1 citations)
- step: 5. Isolate TAC-C-0143 at its main isolator, apply LOTO per HV-PROC-02, and isolate any separately fed control or heater supply listed on the isolation sheet. (2 citations)
- step: 6. Wait at least 5 minutes after isolation before opening the VFD cabinet, and use that time to check the cabinet door seals and the drive cooling air inlet filter from the outside. (1 citations)
- step: 7. Open the cabinet, remove the clear cover over the drive terminal board, prove your CAT III meter on the proving unit, and measure TP1 to TP2, TP1 to PE, and TP2 to PE; all three readings must be below 50 V DC. (1 citations)
- warning: If any DC-bus reading is 50 V DC or more, refit the cover, close the cabinet, wait another 5 minutes, and measure again; if the bus is still not below 50 V DC 15 minutes after isolation, stop because the discharge circuit has failed and escalate to Vastra L2. (2 citations)
- step: 8. Inspect the drive for burn marks, soot, discoloured busbars, smell, cracked IGBT modules, swollen or leaking capacitors, loose or discoloured output cable lugs, water, or condensation on the boards. (1 citations)
- warning: If you find burn marks, a smell of burnt insulation, swollen or leaking capacitors, a cracked IGBT module, melted cable insulation, or any other drive damage, stop, leave the unit locked out, and escalate to Vastra L2 with a High case. (2 citations)
- step: 9. Check that the drive cooling fan turns freely by hand and that the cabinet inlet filter is clean, and replace the filter mat if it is blocked. (1 citations)
- step: 10. Disconnect the motor cables from U, V, and W and move them clear so the drive never sees the insulation test voltage. (1 citations)
- step: 11. Test the motor and cable insulation at 1,000 V DC, each phase to earth, for 60 seconds per phase, and each reading must be above 100 MOhm. (1 citations)
- warning: If any insulation reading is 100 MOhm or less, do not reset, do not try to dry the motor by running it, and go to section 7. (2 citations)
- step: 12. Reconnect the motor cables to U, V, and W in the original order, tighten the lugs to the torque on the label inside the cabinet door, refit the clear cover, and close the cabinet. (1 citations)
- step: 13. With the main isolator still locked off and the cabinet closed, switch on the 24 V auxiliary supply to the drive control board so the keypad shows the latched overcurrent fault. (1 citations)
- step: 14. Set parameter P9.01 to 1, then hold RESET on the drive keypad for 3 seconds until the fault clears; P9.01 returns to 0 by itself after the reset. (1 citations)
- warning: If the fault does not clear after two attempts, stop and call Vastra L2, and do not change any other drive parameter. (2 citations)
- step: 15. Remove the LOTO per HV-PROC-02, restore the main supply, and record the time of re-energisation. (2 citations)
- step: 16. Start TAC-C-0143 in unloaded run and let it run unloaded for 10 minutes, watching the output current the whole time; the motor current must stay below 210 A. (1 citations)
- warning: If the current reaches 210 A or the drive trips during the unloaded run, stop, isolate, and go to section 7 instead of resetting again. (2 citations)
- statement: For TAC-C-0143, the prior E-31 case 00040311 in November 2025 was after a grid dip, was reset per HV-PROC-07, passed an insulation test of 2.4 GOhm, and stayed in service with no repeat that morning. (3 citations)
- statement: For this unit, the repeat-trip rule says that if E-31 returns within 24 hours of a reset, you do not reset again, you leave the unit isolated, escalate to Vastra L2, open a High case, and inform the team lead the same day. (2 citations)
- statement: Appendix A requires one reset record per E-31 attached to the Salesforce work order, including the asset ID, serial, controller firmware, trip time, other alarms in the previous 24 hours, the site power-event answer, isolation details, meter readings, insulation readings, P9.01 status, and the outcome. (1 citations)
- work order: {"asset_id": "TAC-C-0143", "fault_code": "E-31", "summary": "HV-certified reset and post-reset test for E-31 on TAC-C-0143 under HV-PROC-07, with isolation record and Appendix A documentation; escalate if any stop condition occurs or if the fault repeats within 24 hours.", "required_certification": ["cert-hv"], "parts": [], "campaign_code": null, "citations": ["p_f305f74b3d432a456bfd9221", "p_8d53a48ac5150e1416041387", "p_d87019c45d90f5909215147b", "p_38b0191c7d76add6ac55f00f", "p_366157ce50d07095c7e05f34", "p_73515f8d693760063551cb19", "p_97f6b579dddee850c4474a89", "p_8c86e613869f0c822bc18c85"]}

</details>

<details><summary>q06: restricted</summary>

- statement: E-31 on TAC-C-0143 means the VFD saw output current above its peak current limit, and on this VRS-110 the panel cannot reset it. (2 citations)
- statement: The reset is done under HV-PROC-07 by a technician holding HV certification, and you are not certified for that work. (3 citations)
- statement: What you can do instead is record the event log and the unit conditions, note whether there was any power event, photograph the controller screen and log, put that in the case, and raise the work order with Certification required: HV. (3 citations)
- statement: Do not keep resetting it yourself or open the VFD cabinet; if E-31 returns soon after a reset, HV-PROC-07 handles the repeat and when to get Vastra L2 involved. (2 citations)
- work order: {"asset_id": "TAC-C-0143", "fault_code": "E-31", "summary": "E-31 on TAC-C-0143 needs HV-certified reset under HV-PROC-07; record log and conditions, then raise an HV work order.", "required_certification": ["cert-hv"], "parts": [], "campaign_code": null, "citations": ["p_f305f74b3d432a456bfd9221", "p_571ed86283e025f61dfde15b", "p_f9e1145adeb8724d448f344a", "p_0dfe09376c82588dd6d3e10b", "p_ev_d1e7092f1e7aeea1"]}

</details>

<details><summary>q07: abstain</summary>

- notice no_answer: No source you can see covers this for the BX-20. Information for other models (BX-12, NK-600) does not apply and was not used.

</details>

<details><summary>q08: answer</summary>

- statement: E-14 is discharge temperature high: the controller stops the compressor when TS-2 measures more than 110 C at the element outlet, with E-13 shown at 105 C first. (2 citations)
- statement: This VRS-110, TAC-C-0142, serial VRS110-230877, is on firmware 5.0 and is affected by Vastra SB-2026-003, and on firmware 5.0.3 and earlier a failing or drifting TS-2 can be reported as E-14 instead of a sensor fault. (4 citations)
- statement: On 2026-03-12, case 00041207 found E-14 overnight with controller TS-2 at 112 C and the handheld at 96 C at the discharge flange, and replacing TS-2 41-2207 fixed it and brought the readings within 3 C. (2 citations)
- statement: On 2026-07-01, maintenance record 230434 found an E-14 trip with cooler fins plugged on the exhaust side, and blowing them out and restarting kept the unit running for 1 hour on site without another trip. (1 citations)
- statement: On 2026-07-02, case 00042388 found another E-14 after the unit tripped again around 01:30, with ambient at 38 C and controller TS-2 at 113 C versus handheld 102 C at the discharge flange; replacing TS-2 41-2207 again fixed it and brought the readings within 4 C. (2 citations)
- statement: On 2026-07-28, 2026-08-30, and 2026-09-17, records 231058, 231801, and 232346 each logged an E-14 auto restart after cooldown and no callout, so no hardware fix was recorded for those three occurrences. (3 citations)
- statement: The most likely cause is a TS-2 problem on a 5.0 unit that SB-2026-003 says can look like E-14, and this machine also has a TS-2 harness that runs along the freezer exhaust duct and can cook there. (3 citations)
- step: 1. With the unit running loaded and settled, compare TS-2 on the controller with a calibrated contact thermometer at the discharge flange; if the readings are more than 8 C apart, replace TS-2 41-2207, and if the oil cooler stays cold while discharge temperature is high, replace the thermostatic-valve insert. (2 citations)
- step: 2. Also check the normal E-14 causes in the manual: compressor-room ventilation and ambient temperature, cooler and pre-filter mats, oil level and leaks, fan speed reaching 100% above 95 C discharge temperature, and the oil filter and oil age. (1 citations)
- step: 3. Update the firmware to 5.1.0 at the same visit and do not wait for the next scheduled service, because SB-2026-003 says repeated E-14 on firmware 5.0.3 or earlier needs the firmware update and the TS-2 check at once. (2 citations)
- step: 4. If E-14 or E-15 returns after the update, export the event log and send it to Vastra Technical Support with the serial number, and do not replace TS-2 a further time without that information. (2 citations)
- statement: The work needed is a return visit or work order for the firmware 5.1.0 update on TAC-C-0142, plus TS-2 41-2207 on hand for the sensor check or replacement. (3 citations)
- notice bulletin: Vastra SB-2026-003 applies to this unit.
- notice history: Service history from records you can see was used.
- work order: {"asset_id": "TAC-C-0142", "fault_code": "E-14", "summary": "You need a work order to update TAC-C-0142 from firmware 5.0 to 5.1.0 and to check or replace TS-2 41-2207 if the discharge-temperature comparison is out of tolerance.", "required_certification": [], "parts": [{"part_number": "41-2207", "quantity": 1}], "campaign_code": null, "citations": ["p_6fa45bf107f287798dbdcfc7", "p_555df23867026e2357fe3ee0", "p_744d2fe2f13c4c270bf107bf", "p_3b4fd549a8af2a9d2e6afb4b", "p_7fa037f2da6731ad1365e34b"]}

</details>

<details><summary>q09: answer</summary>

- statement: L-03 is low suction pressure: the alarm triggers when suction pressure stays below 2.4 bar for 60 s, and on this NK-600 the bulletin says you must check the EXV position in the service menu before you connect gauges because a sticking expansion valve can produce the same alarm as a low charge. (4 citations)
- statement: Oldest record: on 2024-01-15, case 2400209 for RTM-H-0007 had L-03 on circuit 2 shortly after a winter restart; it cleared by itself after a reset and no action was taken. (1 citations)
- statement: Next: on 2025-01-20, record 2500253 for RTM-H-0007 had L-03 on circuit 2 after a customer winter stop and restart; it was reset and then ran normally, with no action taken. (1 citations)
- statement: Next: on 2025-11-18, case 00040281 for RTM-H-0007 was a closed annual F-gas leak check and found no leak on either circuit. (1 citations)
- statement: Next: on 2026-02-24, case 00041055 for RTM-H-0007 had L-03 on circuit 2 after the winter restart at suction 2.1 bar; visual inspection found no leak, the deficit was under 10% of nameplate charge, and 2.5 kg of R-513A was topped up under KT-WI-14. (3 citations)
- statement: Next: on 2026-09-28, case 00044102 for RTM-H-0007 had L-03 again on circuit 2 at suction 1.9 bar while circuit 1 was normal; the visit found no oil traces at joints or valves and no gauges were connected because the technician was not F-gas certified. (2 citations)
- statement: The likely cause on this machine is the campaign fault: EXV-2 rev 2 can stick partly closed after idle periods, especially after more than 48 hours idle and at low ambient temperature, so the evaporator is starved and the controller sees the same L-03 alarm as low charge. (3 citations)
- statement: Do not top up refrigerant to clear this alarm; the bulletin and manual both say a sticking EXV can look like low charge, and adding refrigerant can overcharge the circuit once the valve frees. (3 citations)
- step: 1. Because RTM-H-0007 is serial NK600-230415 and is in campaign NK-C25-14, you should follow Nordkyl SB-2025-014 first and check the EXV position before any leak-test or charging work. (4 citations)
- step: 2. Let the alarmed circuit run, or restart it, for at least 10 minutes, then read EXV request and EXV position in Service > Circuits > Circuit 1 (or 2) > EXV and write down the values for both circuits. (1 citations)
- step: 3. If the EXV position stays below 15% while the request is higher, the valve is stuck; do not add refrigerant, and replace the valves as described in the campaign. (1 citations)
- step: 4. If the EXV position follows the request within about 5%, the EXV is not the cause of this alarm, so continue with the L-03 troubleshooting in the NK-600 Service Manual and, for this unit, schedule the valve replacement because it is still in campaign. (2 citations)
- step: 5. The campaign work needed is to replace EXV-2 on both circuits with 63-1180 rev 3, replace both filter drier cores with 63-0410, charge by weight to the nameplate charge, fit the new stepper cables, set EXV type to rev 3, run the unit for 30 minutes and confirm EXV position follows request and superheat is stable, then fit the campaign label and log the work and refrigerant quantities in the F-gas record. (2 citations)
- warning: You must stop the unit, isolate it electrically and lock it out before the campaign repair, and the valve body must not exceed 120 C while you braze in the new valve with a nitrogen purge. (1 citations)
- warning: SOP-020 says never top up a circuit to clear L-03 and to escalate if you cannot find the cause, while the old KT-WI-14 used in February allowed a top-up under 10% deficit without a leak test; for RTM-H-0007 you should follow the bulletin and SOP-020, not repeat the February top-up. (3 citations)
- statement: The work needs a work order because this is a campaign correction that requires refrigerant-certified work, parts 63-1180 and 63-0410, and a return visit if the valves are not already on site. (3 citations)
- statement: Work order summary: inspect the EXV first, then replace EXV-2 on both circuits with the campaign parts and complete the campaign claim for NK-C25-14. (2 citations)
- notice bulletin: Nordkyl SB-2025-014 applies to this unit (campaign NK-C25-14).
- notice translated: Some sources are machine translations; the viewer shows the original text.
- notice history: Service history from records you can see was used.
- work order: {"asset_id": "RTM-H-0007", "fault_code": "L-03", "summary": "Campaign repair for NK-C25-14: check EXV first, then replace EXV-2 on both circuits with 63-1180, replace both filter drier cores with 63-0410, recharge by weight, and complete the campaign claim.", "required_certification": ["cert-refrigerant"], "parts": [{"part_number": "63-1180", "quantity": 2}, {"part_number": "63-0410", "quantity": 2}], "campaign_code": "NK-C25-14", "citations": ["p_bc5e16a6074bb0a98d7db510", "p_d825d520c28e9682a85fcc94", "p_03703ad7cbd514fafba64c98", "p_9487c3add93b074b3663bf5c"]}

</details>

<details><summary>q10: answer</summary>

- statement: This is a known BX-12 issue: return idlers from production lot 23-11 have an off-centre bore, so the roller runs slightly eccentric and steers a new belt to the left/drive side until the edge sensor trips C-02 and stops the line. (3 citations)
- statement: The confirmed fix is to replace that return idler with the revised part 77-0419, which has the corrected bore and a blue end cap. (2 citations)
- statement: For this machine, the affected population is BX-12 units built in 2023 and 2024, and your unit FRS-V-0201, serial BX12-240077, falls in that range. (2 citations)
- step: 1. Isolate and lock off the BCU-2 before you work on the idler or take-up. (2 citations)
- step: 2. Check the return idler lot stamp near the tail; if it reads 23-11, replace it with 77-0419. (3 citations)
- step: 3. If you need to run it before the new idler arrives, set both take-up screws back to equal at the position that gives 0.4% elongation, because your tension is already in range and changing it now is not the fix. (3 citations)
- step: 4. Shim the tail pulley bearing on the drive side by 0.5 mm using one stainless shim piece behind the bearing block, between the block and the take-up slide. (1 citations)
- step: 5. Run the belt empty at normal speed and check the tracking after three belt revolutions; if it is still walking after three revolutions, stop and ring Belton Technical Support. (3 citations)
- step: 6. When you fit 77-0419, remove the shim, set the take-up even again, and re-check tracking after three revolutions. (2 citations)
- step: 7. If the idler checks out, the manual says to compare take-up equalization, then frame square, then pulley-face residue or wear, and to clean pulley faces with warm water only; never use solvent on the lagging. (1 citations)
- step: 8. If the belt still tracks to one side after those checks, Belton says to stop and call Technical Support with the serial number, the direction of tracking, and the turns already applied at each take-up. (1 citations)
- statement: A service record for this unit, case 00041750, shows the same symptom on FRS-V-0201 in May 2026, that Belton confirmed it as a known issue, and that fitting 77-0419 restored correct tracking. (3 citations)
- statement: Another record for the same unit, maintenance record 229186, shows the interim fix was removed, the take-up was left even, and tracking was OK after the 77-0419 change. (1 citations)
- work order: {"asset_id": null, "fault_code": null, "summary": "Replace the BX-12 return idler with revised part 77-0419 and verify tracking after installation.", "required_certification": [], "parts": [{"part_number": "77-0419", "quantity": 1}], "campaign_code": null, "citations": ["p_82ab900842586b83c90077df", "p_ev_f97f6737619254af", "p_633865cb17cc8547a471da41"]}

</details>

<details><summary>p1: restricted</summary>

- statement: On an NK-600, the situation is a low refrigerant charge/low suction pressure condition that can present as L-03, and if the unit serial is NK600-220001 to NK600-231999 you must also treat SB-2025-014 as first priority because EXV-2 rev 2 can stick and mimic an undercharge. (3 citations)
- statement: Only certified persons may recover refrigerant, and the work that opens the refrigerant circuit may only be done by refrigerant-certified technicians, so this job must be assigned to a certified technician. (2 citations)
- statement: What you may do instead is record the alarm and unit details and raise a work order for the certified technician, including the serial number so the bulletin status can be checked before any refrigerant work begins. (3 citations)
- work order: {"asset_id": null, "fault_code": null, "summary": "Raise a work order for a refrigerant-certified technician to handle the NK-600 low-charge/L-03 condition under SOP-020, with bulletin check first for serials NK600-220001 to NK600-231999.", "required_certification": ["cert-refrigerant"], "parts": [], "campaign_code": null, "citations": ["p_67480646ec1f6c672eb5885a", "p_c182998a61a4d7ba4fc9ba8e", "p_9487c3add93b074b3663bf5c", "p_ec8f6f9f6c829f8bf0c0e905", "p_aada6e8039d18eb9ea812ebe"]}

</details>

<details><summary>p2: answer</summary>

- warning: Never top up an NK-600 circuit to clear a low suction pressure alarm; if you cannot find the cause, stop and escalate. (1 citations)
- warning: If your NK-600 serial number is in campaign NK-C25-14 and the unit has an L-03 alarm, check the EXV position in the service menu before you add refrigerant, because a sticking expansion valve can give the same alarm as a low charge and refrigerant will not fix it. (3 citations)
- statement: For an NK-600, a circuit that is short of charge has a leak, and adding refrigerant without finding and repairing the leak is not an approved repair. (1 citations)
- step: 1. Check the unit serial number against open service bulletins and campaigns for the model before you start. (2 citations)
- step: 2. Read the alarm history on the controller and note which circuit alarmed, when it alarmed, and the suction and discharge pressures at the time. (2 citations)
- step: 3. Check for non-leak causes of low suction pressure: an iced evaporator, low chilled water flow, a dirty condenser coil, a blocked filter drier with a temperature drop across the drier above 3 C, or an expansion valve not modulating. (1 citations)
- step: 4. Inspect for oil stains at joints, flare nuts, service valves, and the compressor, because oil marks the place where refrigerant escapes. (1 citations)
- step: 5. Run the unit and leak test both circuits with a calibrated electronic leak detector with sensitivity 3 g/year or better, moving the probe at no more than 5 cm per second below joints because R-513A is heavier than air. (2 citations)
- step: 6. Confirm every indication with bubble solution before you open the circuit. (1 citations)
- step: 7. If no leak is found but the charge is low, do not top up; record the result, tag the unit, and escalate to the team lead for an ultrasonic or tracer-gas test. (1 citations)
- step: 8. Recover the refrigerant from the affected circuit into a labelled recovery cylinder and weigh and record the recovered amount. (2 citations)
- step: 9. Repair the leak, and replace the filter drier core 63-0410 whenever the circuit has been opened. (2 citations)
- step: 10. Fit the gauge manifold and nitrogen regulator, and never pressurize directly from the nitrogen cylinder without a regulator. (1 citations)
- step: 11. Pressurize in steps to 3 bar and check for audible leaks, then to 10 bar and check with bubble solution, then pressurize with dry nitrogen to 15 bar and hold for 30 minutes. (1 citations)
- step: 12. Assess the pressure-test result against Appendix C, and record the start and end pressure and the ambient temperature at start and end because nitrogen pressure changes with temperature. (1 citations)
- step: 13. Release the nitrogen to atmosphere outdoors. (1 citations)
- step: 14. Connect a vacuum pump with short, large-bore hoses, remove the Schrader cores for faster evacuation, evacuate to below 500 microns, then isolate the pump and hold for 15 minutes. (1 citations)
- step: 15. If the vacuum rises above 1,000 microns, there is moisture or a leak, and you must return to the repair and pressure-test step. (1 citations)
- step: 16. Charge by weight to the nameplate charge of the circuit as liquid through the liquid line service valve, then start the circuit and check suction pressure, discharge pressure, superheat, and subcooling against the values in the manufacturer's manual. (1 citations)
- step: 17. Leak test the repaired joint again with the unit running, and label the unit with the refrigerant type, the total charge, and the date. (1 citations)
- statement: For campaign NK-C25-14, replace the EXV-2 valve on both circuits with 63-1180 rev 3, replace both filter drier cores with 63-0410, fit the new stepper cable, set Service > Configuration > Circuit 1 > EXV type to "rev 3", repeat for circuit 2, and after 30 minutes verify that EXV position follows the request and that superheat is stable. (2 citations)
- statement: The campaign applies to NK-600 serials NK600-220001 to NK600-231999 in EU deliveries, where EXV-2 rev 2 is fitted; NK600-232000 and later with EXV-2 rev 3 are not affected. (1 citations)
- statement: Only certified persons may check for leaks, recover, install, service, or repair the circuits, and in the EU the repair must be checked by a certified person within one month to confirm it is effective. (1 citations)
- work order: {"asset_id": null, "fault_code": null, "summary": "Recover the affected circuit, repair the leak or complete campaign NK-C25-14 if the serial is in range, replace the filter drier core, evacuate, and recharge by weight; certified refrigerant work is required.", "required_certification": ["cert-refrigerant"], "parts": [{"part_number": "63-0410", "quantity": 1}, {"part_number": "63-1180", "quantity": 2}], "campaign_code": null, "citations": ["p_03703ad7cbd514fafba64c98", "p_67480646ec1f6c672eb5885a", "p_bc5e16a6074bb0a98d7db510", "p_d825d520c28e9682a85fcc94"]}

</details>

<details><summary>p3: restricted</summary>

- statement: E-31 means the drive saw more current than it allows on the VRS-110, and the panel reset is disabled for it; reset work is done under HV-PROC-07 by a technician holding the HV certification, which you do not have for this task. (3 citations)
- statement: You must not open the VFD cabinet or keep resetting it; if the fault repeats soon after a reset, it is not treated as a grid event and HV-PROC-07 covers the repeat case, including when to involve Vastra L2. (1 citations)
- statement: What you may do instead is record the event log and the conditions, note what the unit was doing and whether there was a power event, photograph the controller screen and log, put that in the case, and raise the work order with Certification required: HV. (3 citations)
- work order: {"asset_id": "TAC-C-0143", "fault_code": "E-31", "summary": "E-31 on TAC-C-0143 needs HV-certified reset under HV-PROC-07; collect log and site details, then raise the work order with Certification required: HV.", "required_certification": ["cert-hv"], "parts": [], "campaign_code": null, "citations": ["p_f305f74b3d432a456bfd9221", "p_f1f4e9b268c06d83d61b9ab9", "p_f9bf0ab1756f00082a9b4def", "p_af9b3b0d23d2bc23c3ea59da", "p_ev_19c19d86f67ed10a"]}

</details>

<details><summary>c1: clarify</summary>


</details>

<details><summary>a1: abstain</summary>

- notice no_answer: No machine with the ID FRS-P-9999 is in the fleet records.

</details>

<details><summary>n1: abstain</summary>

- notice not_visible: Information on this is not visible to you. Ask your team lead or a technician trained on this equipment.

</details>

<details><summary>m1: restricted</summary>

- statement: E-31 on a VRS-110 means the drive saw more current than it allows, and the panel reset is disabled; the reset is done under HV-PROC-07 by a technician with HV certification, which you do not have. (4 citations)
- statement: You may read the event log, note every code in the hour before the trip with times, record what the unit was doing and whether there was a power event, photograph the controller screen and log, and put all of that in the case. (1 citations)
- statement: Then raise the work order with Certification required: HV and tell the site contact the unit is out until an HV tech arrives; if E-31 comes back soon after a reset, do not keep resetting it and escalate through HV-PROC-07 with Vastra L2 involvement as directed. (3 citations)
- work order: {"asset_id": null, "fault_code": "E-31", "summary": "E-31 on VRS-110 requires HV-certified reset under HV-PROC-07; collect log and site details, then raise an HV work order.", "required_certification": ["cert-hv"], "parts": [], "campaign_code": null, "citations": ["p_f305f74b3d432a456bfd9221", "p_f9e1145adeb8724d448f344a", "p_f1f4e9b268c06d83d61b9ab9", "p_0dfe09376c82588dd6d3e10b", "p_d8f19cd2ee7f8ebe2652fabf"]}

</details>

<details><summary>t1: clarify</summary>


</details>

<details><summary>f1: answer</summary>

- statement: For an HCP-200 in standard design, the impeller-to-casing clearance spec is 0.38 to 0.50 mm diametral. (1 citations)
- statement: This value applies to the standard design; special designs use the order confirmation. (2 citations)
- statement: If the clearance exceeds the maximum in table 3.1, you must renew the wear rings, because increasing clearance reduces flow rate and efficiency. (2 citations)
- notice translated: Some sources are machine translations; the viewer shows the original text.

</details>

<details><summary>f2: restricted</summary>

- statement: E-31 on TAC-C-0143 means VFD overcurrent: the drive saw output current above its peak current limit and switched off the output immediately. (2 citations)
- warning: This reset is done under HV-PROC-07 by an electrically qualified HV-certified technician, and you are not certified for that work, so do not open the VFD cabinet or try to reset it from the panel; if E-31 repeats soon after a reset, do not keep resetting it and raise the work order for HV support. (3 citations)
- statement: What you may do instead is record the event log codes and times from the hour before the trip, note what the unit was doing, ask the site whether there was a power event, photograph the controller screen and log, and put that information in the case before raising the HV work order and telling the site the unit is out until an HV tech arrives. (2 citations)
- work order: {"asset_id": "TAC-C-0143", "fault_code": "E-31", "summary": "TAC-C-0143 has E-31 VFD overcurrent and needs an HV-certified reset under HV-PROC-07.", "required_certification": ["cert-hv"], "parts": [], "campaign_code": null, "citations": ["p_f305f74b3d432a456bfd9221", "p_571ed86283e025f61dfde15b", "p_0dfe09376c82588dd6d3e10b", "p_ev_d1e7092f1e7aeea1"]}

</details>

<details><summary>f3: answer</summary>

- statement: For FRS-P-0012, use 38 N-m on the casing bolts after the seal change if the pump has a Version 2 casing cover; if it has the original Version 1 cover, use 45 N-m. (4 citations)
- warning: Do not guess from the nameplate on this pump: the nameplate does not show the casing version, and a pump before HCP350-240001 that has been fitted with a replacement cover must be treated as a Version 2 pump for this bulletin. (1 citations)
- statement: A Version 2 HCP-350 casing joint is tightened in a cross pattern in two passes: first to approximately 20 N-m, then to 38 N-m, using a calibrated torque wrench. (2 citations)
- statement: The older IOM Rev D value of 45 N-m applies only to HCP-350 pumps with serial numbers before HCP350-240001 and is still the manual value for Version 1 covers. (3 citations)
- statement: For this unit, the fleet record says the bulletin status for Halden SB-2025-009 is check_on_site, so you need to verify the cover hardware before you torque the casing bolts. (1 citations)
- conflict Casing bolt torque for FRS-P-0012: 38 N-m applies to pumps with Version 2 casing covers and to pumps before HCP350-240001 that have been fitted with a replacement cover. vs 45 N-m applies only to pumps with serial numbers before HCP350-240001 that still use the original Version 1 cover. (preferred None)
- notice check_on_site: Halden SB-2025-009: whether it applies depends on a condition to check at the machine: depends on the unit's hardware: A pump before HCP350-240001 that has been fitted with a replacement cover is to be treated as a Version 2 pump for all purposes of this bulletin.
- notice bulletin: Halden SB-2025-018 applies to this unit.

</details>

