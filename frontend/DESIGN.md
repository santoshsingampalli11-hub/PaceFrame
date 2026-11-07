# Kinematic Laboratory — V1 screen notes

The repository did not contain a Stitch HTML export or screenshot. The interface uses the written Kinematic Laboratory reference: navy base `#101820`, emerald `#2FE19A`, slate `#64748B`, and blue `#38BDF8`. Anvers is used for headings. Interface text and numbers use the system sans and monospace fonts. The five routes and scientific limits are unchanged.

## Screens

1. Upload & Session — `/` and `/sessions/:id`
2. Video & Pose Review — `/sessions/:id/review`
3. Event Annotation — `/sessions/:id/events`
4. Knee Kinematics — `/sessions/:id/knee`
5. Analysis Report — `/sessions/:id/report`

Steps 2–5 stay disabled until a session id exists.

## What each screen may show

Upload stores one clip and shows inspection fields. It does not mean the delivery has been measured.

Review shows original decoded frames and a pose job. Overlay images exist only for the indexes requested before the job, at most 8. Detection counts are not accuracy.

Annotation marks BFC optionally and FFC and Release by hand on the frame that is actually displayed. Existing saved labels are read-only.

Knee measurement shows 2D angles from the stored manual frames, or Unavailable. It does not draw a trajectory or a score.

The report repeats stored session, label, pose-count, and measurement JSON. Download CSV and Download JSON are enabled only when a measurement report exists.

## Layout

Desktop keeps the sidebar. Below 900px the sidebar is behind Menu. Controls stack. The frame image stays full width of its panel.
