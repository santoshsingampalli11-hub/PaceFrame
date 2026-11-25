# Not built, and why

This list covers the submitted PaceFrame application. It does not add findings that are not in the repository.

| Item | State in this repository | Why it is not a delivered result |
|---|---|---|
| Three-dimensional joint angles, ground reaction forces, joint loading, tissue forces, and injury prediction | Not built | One side-on phone camera cannot support those measurements. The project rules forbid presenting them as results. |
| Automatic back-foot contact, front-foot contact, and ball release | Not used by the application | The web workflow stores only frames a person marks. `search_contact_candidates` is an experimental image-space helper. Its default is to abstain, release detection is not implemented, and the module states that a still foot in the image is not confirmed ground contact. It is not called by the API. |
| Accuracy statistic or completed comparison with a manual reference angle | Not in the repository | `docs/measurement_validation/MEASUREMENT_EVIDENCE.md` says stored pixel evidence lets a later checker recompute the stored angle. That check does not prove the pixels sit on the joint. The dataset evaluation tables in this tree are templates, not a finished validation set. |
| User accounts, passwords, and private session ownership | Not built | This prototype has no authentication. A session id is not permission to view someone else's video. Public anonymous hosting was therefore left blocked. |
| Verified Docker deployment and public HTTPS hosting | Files only | `deploy/` contains compose and Docker files. No container image was built or run for this submission, and no public tunnel or domain was configured. |
| PDF download in the web application | Not connected to the API or the page | `backend/app/pilot/measurement_pdf.py` can render a report for tests. The running page downloads the stored measurement as JSON and CSV. |
| Multiple server workers, a shared job queue, and a shared rate limit | Not built | Pose review and measurement are in-process. The deployment notes require one Uvicorn process because a second process would not share those limits. |
| Pose model inside Git | Intentionally absent | `*.task` is gitignored. A clone needs the MediaPipe file documented in `backend/README.md`: `backend/models/pose_landmarker_full.task`, 9,398,198 bytes, SHA-256 `5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1`. |
| Formal multi-participant interview study | Not completed | `docs/COACH_CONSULTATION.md` is a retrospective summary of one informal consultation. The offered domain knowledge was not used to validate V1 measurements. |

The delivered measurement remains the manual 2D front-knee angle at the confirmed front-foot-contact and release frames.
