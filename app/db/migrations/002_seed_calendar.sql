-- Migration 002: seed the Wayanad Robusta coffee-year phenology calendar.
-- month ranges are inclusive and may wrap across year end (harvest = 12-2).
-- Edit freely: the home screen reads whatever is in calendar_events.

INSERT INTO calendar_events (phenostage, month_start, month_end, typical_activities, notes) VALUES
 ('harvest',        12, 2, 'Picking Dec-Feb; pulping, washing, drying and curing; staggered harvest rounds', 'Peak picking Jan; Robusta cherries ripe Nov-Jan'),
 ('blossom',         2, 3, 'Blossom triggered by pre-monsoon showers; watch canopy greenness (NDRE) and moisture stress', 'Showers in Feb-Mar trigger flowering; critical NDRE window'),
 ('fruit_set',       4, 5, 'Fruit set and early development; pest & disease control around April; first fertilizer round synced with weeding', 'April pest window: white stem borer, berry borer scouting'),
 ('monsoon',         6, 9, 'SW monsoon; standing-water and erosion watch (Sentinel-1 layer); soil conservation; pruning window Aug-Sep', 'Optical satellites blinded Jun-Sep; S1 VH carries the signal'),
 ('post_monsoon',   10, 11, 'Indian coffee year starts Oct 1; second fertilizer round synced with weeding; composting; shade management', 'Fertilizer split: ~May-Jun and ~Sep-Oct for Robusta');
