# Problem statement

Cricket fast-bowling coaches and analysts need a repeatable way to look at one delivery from a side-on smartphone video. Laboratory motion capture can measure three-dimensional joint motion, but it is not available for this project and it is not what a phone recording provides.

PaceFrame V1 is a local prototype for that narrower problem. A person uploads one standardized side-on video. The application reads the file, estimates a 2D body pose, and asks a person to mark front-foot contact and ball release. Back-foot contact is optional. The person also chooses the bowler's anatomical front leg and confirms that the marks belong to that video.

At those two marked frames, the application calculates one unsigned 2D hip–knee–ankle angle on the confirmed front leg. The vertex is the knee. The result is in degrees from 0 to 180. The stored report can include the pixel coordinates used for that calculation. If a required landmark is missing, the angle is unavailable. It is not stored as zero.

The prototype does not claim a three-dimensional joint angle, a ground reaction force, joint loading, tissue force, a technique score, or an injury prediction. A file hash shows that the stored video bytes match the session record. It does not prove that the camera view, the bowler, or the angle is scientifically accurate.

This repository does not contain a completed accuracy study. `docs/COACH_CONSULTATION.md` is a retrospective note of one informal consultation. That consultation was not used to validate the measurements. The other limits are listed in `docs/NOT_BUILT_AND_WHY.md`.
