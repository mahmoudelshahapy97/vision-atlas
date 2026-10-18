-- ---------------------------------------------------------------------------
-- Vision Project Atlas : queries
--
-- A reference, not a script: the main statements the API issues, with the
-- service function and endpoint that issue each one. Parameters are asyncpg
-- style ($1, $2, ...). The live SQL is in backend/app/services/*_service.py;
-- when the two disagree, the service is right and this file is stale.
--
--   1. catalog     domains, task types, technologies
--   2. projects    listing, facets, detail, admin writes
--   3. progress    status and notes, board statistics
--   4. accounts    sign-in, registration
--   5. lab runs    submission, worker updates, history, recovery
--   6. models      uploaded weights
--   7. operations  handy by hand
-- ---------------------------------------------------------------------------


-- ===========================================================================
-- 1. CATALOG
-- ===========================================================================

-- :name catalog_service.list_domains
-- GET /api/domains
SELECT d.id, d.code, d.name, d.slug, COUNT(p.id) AS project_count
FROM domain d
LEFT JOIN project p ON p.domain_id = d.id
GROUP BY d.id
ORDER BY d.code;

-- :name catalog_service.list_task_types
-- GET /api/task-types
SELECT t.id, t.code, t.name, t.metric,
       COALESCE((SELECT array_agg(s.text ORDER BY s.position)
                 FROM task_step s WHERE s.task_type_id = t.id), '{}') AS steps,
       (SELECT COUNT(*) FROM project p WHERE p.task_type_id = t.id) AS project_count
FROM task_type t
ORDER BY t.id;

-- :name catalog_service.list_technologies
-- GET /api/technologies?limit=
SELECT tc.name, COUNT(pt.project_id) AS project_count
FROM technology tc
JOIN project_technology pt ON pt.technology_id = tc.id
GROUP BY tc.id
ORDER BY project_count DESC, tc.name
LIMIT $1;

-- :name catalog_service.get_or_create_technology  (inside the project write transaction)
SELECT id FROM technology WHERE lower(name) = lower($1);
INSERT INTO technology (name) VALUES ($1) RETURNING id;


-- ===========================================================================
-- 2. PROJECTS
-- ===========================================================================

-- :name project_service.list_projects
-- GET /api/projects?q=&domain=&task=&level=&picks=&status=&tech=&sort=&page=&size=
-- One statement per page: project + domain + task type + ordered technologies
-- + the caller's progress ($1 = user id, NULL when signed out). The WHERE
-- clause is assembled from the filters; one word of `q` looks like this:
SELECT p.id, p.title, p.slug, p.description, p.level, p.is_pick, p.pick_reason, p.caution, p.lab,
       p.domain_id, d.code AS domain_code, d.name AS domain_name, d.slug AS domain_slug,
       p.task_type_id, t.code AS task_code, t.name AS task_name, t.metric AS task_metric,
       COALESCE((SELECT array_agg(tc.name ORDER BY pt.position, tc.name)
                 FROM project_technology pt
                 JOIN technology tc ON tc.id = pt.technology_id
                 WHERE pt.project_id = p.id), '{}') AS technologies,
       up.status AS progress_status, up.notes AS progress_notes, up.updated_at AS progress_updated_at
FROM project p
JOIN domain d ON d.id = p.domain_id
JOIN task_type t ON t.id = p.task_type_id
LEFT JOIN user_project up ON up.project_id = p.id AND up.user_id = $1
WHERE d.code = $2
  AND (lower(p.title) LIKE $3 ESCAPE '\' OR lower(p.description) LIKE $3 ESCAPE '\'
       OR lower(d.name) LIKE $3 ESCAPE '\' OR lower(t.name) LIKE $3 ESCAPE '\'
       OR EXISTS (SELECT 1 FROM project_technology pt JOIN technology tc ON tc.id = pt.technology_id
                  WHERE pt.project_id = p.id AND lower(tc.name) LIKE $3 ESCAPE '\'))
ORDER BY p.id
LIMIT $4 OFFSET $5;

-- status=active (planned, building or done) for the signed-in user:
--   p.id IN (SELECT project_id FROM user_project WHERE user_id = $n AND status <> 'idea')

-- :name project_service.facets
-- GET /api/projects/facets   (each dimension leaves its own filter out)
SELECT d.code AS key, COUNT(*) AS n
FROM project p
JOIN domain d ON d.id = p.domain_id
JOIN task_type t ON t.id = p.task_type_id
WHERE p.level = $1          -- every active filter except domain
GROUP BY d.code;

-- :name project_service.get_project
-- GET /api/projects/{id-or-slug}: the select above with WHERE p.id = $2 (or p.slug = $2), then
SELECT COALESCE((SELECT array_agg(text ORDER BY position) FROM task_step
                 WHERE task_type_id = $2), '{}') AS steps,
       (SELECT MAX(id) FROM project WHERE id < $1) AS prev_id,
       (SELECT MIN(id) FROM project WHERE id > $1) AS next_id;

-- :name project_service.create_project
-- POST /api/projects   (admin; one transaction with the technology links)
INSERT INTO project (title, slug, description, domain_id, task_type_id, level,
                     is_pick, pick_reason, caution, lab)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
RETURNING id;

DELETE FROM project_technology WHERE project_id = $1;
INSERT INTO project_technology (project_id, technology_id, position) VALUES ($1, $2, $3);

-- :name project_service.update_project
-- PATCH /api/projects/{id}   (SET list built from the fields sent)
UPDATE project SET title = $1, slug = $2, updated_at = NOW() WHERE id = $3;

-- :name project_service.delete_project
-- DELETE /api/projects/{id}
DELETE FROM project WHERE id = $1;


-- ===========================================================================
-- 3. PROGRESS
-- ===========================================================================

-- :name progress_service.set_progress
-- PUT /api/projects/{id}/progress   (status 'idea' + blank notes deletes the row instead)
INSERT INTO user_project (user_id, project_id, status, notes)
VALUES ($1, $2, $3, $4)
ON CONFLICT (user_id, project_id)
DO UPDATE SET status = EXCLUDED.status, notes = EXCLUDED.notes, updated_at = NOW()
RETURNING project_id, status, notes, updated_at;

-- :name progress_service.reset
-- DELETE /api/projects/{id}/progress
DELETE FROM user_project WHERE user_id = $1 AND project_id = $2;

-- :name progress_service.stats  (by domain)
-- GET /api/me/stats
SELECT d.code, d.name,
       COUNT(DISTINCT p.id) AS total,
       COUNT(up.project_id) FILTER (WHERE up.status <> 'idea') AS started,
       COUNT(up.project_id) FILTER (WHERE up.status = 'done') AS done
FROM domain d
JOIN project p ON p.domain_id = d.id
LEFT JOIN user_project up ON up.project_id = p.id AND up.user_id = $1
GROUP BY d.code, d.name
ORDER BY d.code;


-- ===========================================================================
-- 4. ACCOUNTS
-- ===========================================================================

-- :name user_service.get_by_email
-- POST /api/auth/login, POST /api/auth/register (duplicate check)
SELECT * FROM app_user WHERE email = $1;

-- :name user_service.create_user
-- POST /api/auth/register, and the bootstrap admin at startup
INSERT INTO app_user (email, name, password_hash, role)
VALUES ($1, $2, $3, $4)
RETURNING id, email, name, role, is_active, token_version, last_login, created_at, updated_at;

-- :name user_service.get_by_id
-- every authenticated request (api/deps.py re-reads the row and compares
-- is_active and the token's tv claim with token_version)
SELECT id, email, name, role, is_active, token_version, last_login, created_at, updated_at
FROM app_user WHERE id = $1;

-- :name user_service.bump_token_version
-- POST /api/auth/logout-all; also set_password and update_user (role/active change)
UPDATE app_user SET token_version = token_version + 1, updated_at = NOW() WHERE id = $1;

-- :name user_service.count_admins
-- the last-admin guard in PATCH/DELETE /api/users/{id}
SELECT COUNT(*) FROM app_user WHERE role = 'admin' AND is_active AND id <> COALESCE($1, -1);

-- :name auth_service.token_response
-- every sign-in, registration, refresh and password change records the new refresh token
INSERT INTO refresh_session (user_id, jti, expires_at, user_agent, ip_address)
VALUES ($1, $2, $3, $4, $5);

-- :name auth_service.refresh (rotate)
-- POST /api/auth/refresh: 0 rows means another refresh already used this token
UPDATE refresh_session SET revoked_at = NOW(), rotated = TRUE WHERE jti = $1 AND revoked_at IS NULL;

-- :name auth_service.revoke_sessions
-- sign out everywhere, password change or reset, deactivation, and a replayed refresh token
UPDATE refresh_session SET revoked_at = NOW() WHERE user_id = $1 AND revoked_at IS NULL;


-- :name model_service._VISIBLE
-- GET /api/models, a lab's model picker, POST /api/runs: public, yours, or shared
-- with an active workspace you belong to
SELECT ml.*, ws.name AS workspace_name
FROM ml_model ml LEFT JOIN workspace ws ON ws.id = ml.workspace_id
WHERE ml.is_public OR ($1::int IS NOT NULL AND (
    ml.owner_id = $1
    OR ml.workspace_id IN (
        SELECT m.workspace_id FROM workspace_member m JOIN workspace w ON w.id = m.workspace_id
        WHERE m.user_id = $1 AND w.is_active
    )
));

-- :name workspace_service.list_for_user
-- GET /api/workspaces/mine (system admins get every workspace instead)
SELECT w.*, m.role AS my_role,
       (SELECT COUNT(*) FROM workspace_member x WHERE x.workspace_id = w.id) AS member_count
FROM workspace w JOIN workspace_member m ON m.workspace_id = w.id AND m.user_id = $1
WHERE w.is_active
ORDER BY w.name;

-- :name workspace_service.role_of
-- every workspace-scoped request (api/deps.py workspace_access)
SELECT role FROM workspace_member WHERE workspace_id = $1 AND user_id = $2;


-- :name camera_service.list_runnable
-- the camera supervisor (every few seconds) and startup: enabled cameras of
-- active workspaces, with the weights path of an uploaded model they use
SELECT c.*, m.file_path AS model_path
FROM camera c
JOIN workspace w ON w.id = c.workspace_id AND w.is_active
LEFT JOIN ml_model m ON c.params ? 'model' AND c.params->>'model' = 'custom:' || m.id
WHERE c.enabled
ORDER BY c.id;


-- ===========================================================================
-- 5. LAB RUNS
-- ===========================================================================

-- :name run_service.count_in_flight
-- POST /api/runs   (per-user limit MAX_RUNS_IN_FLIGHT)
SELECT COUNT(*) FROM inference_run WHERE user_id = $1 AND status = ANY($2::text[]);

-- :name run_service.create_run
-- POST /api/runs
INSERT INTO inference_run (public_id, user_id, project_id, pipeline, status, progress, params, inputs)
VALUES ($1, $2, $3, $4, 'queued', 0, $5, $6)
RETURNING *;

-- :name run_service.mark_running / set_progress / finish
-- issued from the lab worker threads (app/vision/runner.py) on the API's event loop
UPDATE inference_run SET status = 'running' WHERE id = $1 RETURNING *;
UPDATE inference_run SET progress = $2 WHERE id = $1 AND status = 'running';
UPDATE inference_run
SET status = $2, result = $3, error = $4, duration_ms = $5, finished_at = NOW(),
    progress = CASE WHEN $2 = 'done' THEN 1 ELSE progress END
WHERE id = $1;

-- :name run_service.list_for_user
-- GET /api/runs?project_id=&limit=
SELECT r.*, p.title AS project_title
FROM inference_run r
LEFT JOIN project p ON p.id = r.project_id
WHERE r.user_id = $1 AND ($2::int IS NULL OR r.project_id = $2)
ORDER BY r.created_at DESC, r.id DESC
LIMIT $3;

-- :name run_service.recover_interrupted
-- API startup: runs a restart cut short can't resume
UPDATE inference_run
SET status = 'error', error = 'The server restarted before this run finished. Please run it again.'
WHERE status = ANY($1::text[]);


-- ===========================================================================
-- 6. MODELS
-- ===========================================================================

-- :name model_service.list_visible
-- GET /api/models   (shared models plus the caller's own)
SELECT * FROM ml_model
WHERE (is_public OR ($1::int IS NOT NULL AND owner_id = $1))
ORDER BY created_at DESC, id DESC;

-- :name model_service.create_model
-- POST /api/models/upload
INSERT INTO ml_model (owner_id, project_id, name, task, file_path, classes, size_bytes, is_public)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
RETURNING *;


-- ===========================================================================
-- 7. OPERATIONS (by hand)
-- ===========================================================================

-- Make an existing account an admin.
-- UPDATE app_user SET role = 'admin' WHERE email = 'you@example.com';

-- Runs per pipeline, slowest first.
SELECT pipeline, COUNT(*) AS runs,
       COUNT(*) FILTER (WHERE status = 'error') AS failed,
       ROUND(AVG(duration_ms)) AS avg_ms
FROM inference_run
GROUP BY pipeline
ORDER BY avg_ms DESC NULLS LAST;

-- Projects without a lab.
SELECT id, title FROM project WHERE lab IS NULL ORDER BY id;
