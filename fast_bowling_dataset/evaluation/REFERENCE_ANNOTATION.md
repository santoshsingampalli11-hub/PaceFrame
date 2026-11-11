# Independent reference annotation

This is how a second person marks the front-knee angle on a decoded frame. The mark is an image measurement. It is not a 3D joint angle and not laboratory ground truth.

The automatic angle is defined in `backend/app/biomechanics/front_knee.py` and calculated by `angle_abc_degrees` in `backend/app/biomechanics/geometry.py`. The reference uses that same definition. It does not use a different joint convention.

## What the annotator is given

- The original video file and its SHA-256.
- The decoded frame index already chosen for FFC or Release. Frame 0 is the first decoded frame. Do not use a video player's time as the frame number.
- The anatomical front leg, `left` or `right`. That is the bowler's side, not the left or right side of the picture.
- The decoded image for that frame, with its width and height in pixels.

The annotator marks the image. Do not copy MediaPipe landmark coordinates, normalized pose coordinates, or the analyzer's angle into this sheet. Do not open the pose overlay as the source of the points.

## Points

Mark three points on the named front leg:

- Hip: the hip joint centre as seen in the image.
- Knee: the knee joint centre. This is the vertex.
- Ankle: the ankle joint centre, not an arbitrary point on the shoe.

Use image pixels. The origin is the top-left of the decoded frame. `x` increases to the right. `y` increases downward. This is the same pixel space as `x_normalized * image_width` and `y_normalized * image_height` in the analyzer. Record the pixels you clicked, not a normalized fraction.

If a joint is hidden, ambiguous, or outside the image, leave that point and `reference_angle_degrees` blank. Write why in `ambiguity_notes`. Do not guess a hidden joint, and do not enter 0.

## Angle

The angle is the unsigned angle at the knee, in degrees, from 0 to 180.

With hip `H`, knee `K`, and ankle `A` in pixels:

- vector from knee to hip: `(H.x - K.x, H.y - K.y)`
- vector from knee to ankle: `(A.x - K.x, A.y - K.y)`
- cosine = dot product of those vectors, divided by the product of their lengths
- clip the cosine to the range -1 to 1
- angle = `acos(cosine)`, converted from radians to degrees

If either vector has length zero, the angle is undefined. Leave it blank.

The existing function `angle_abc_degrees(hip, knee, ankle)` is this calculation. A reference computed that way can later be passed to `compare_front_knee_angle` in `backend/app/biomechanics/angle_comparison.py`. Signed error there is the automatic angle minus the reference angle.

## What to record

One row in `independent_reference_angles.csv` for each phase that was marked:

- `bowler_id`, `delivery_id`, and `video_sha256` of the file that was viewed
- `phase`: `FFC` or `Release`
- `frame_index`: the zero-based decoded frame that was marked
- `front_leg`: `left` or `right`
- `image_width_px` and `image_height_px` of that decoded frame
- `hip_x_px`, `hip_y_px`, `knee_x_px`, `knee_y_px`, `ankle_x_px`, `ankle_y_px`
- `reference_angle_degrees`: the angle from the formula above, or blank
- `annotator_id`: initials or a role, not a full name
- `ambiguity_notes`: what was hard to see, or blank

Do not change the system's saved event frames while writing this sheet. A different frame choice belongs in `independent_event_frames.csv`.
