-- PlantCraft 0.5.0 (a794c5d): the tables a fresh installation of that release has.
-- Written by dev/schema-snapshot/dump.py; never edited (tests/test_upgrade_schema.py).
CREATE TABLE app_contributions (
        app TEXT PRIMARY KEY,
        version TEXT NOT NULL DEFAULT '',
        body_json TEXT NOT NULL DEFAULT '{}',
        unknown_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    );
CREATE TABLE app_install_settings (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
CREATE TABLE app_keys (
        key_id TEXT PRIMARY KEY,
        app_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        key_hash TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        revoked_at TEXT,
        revoked_by TEXT,
        last_used_at TEXT
    );
CREATE TABLE app_knowledge (
        app_id TEXT NOT NULL,
        ref TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        subjects_json TEXT NOT NULL DEFAULT '[]',
        url TEXT,
        transient INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, ref)
    );
CREATE TABLE app_llm_calls (
        app TEXT NOT NULL,
        day TEXT NOT NULL,
        calls INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (app, day)
    );
CREATE TABLE app_result_history (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        score REAL,
        usable INTEGER,
        value REAL,
        summary TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL,
        recorded_at TEXT NOT NULL
    );
CREATE TABLE app_results (
        app_id TEXT NOT NULL,
        subject TEXT NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        score REAL,
        usable INTEGER,
        value REAL,
        summary TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}',
        at TEXT NOT NULL,
        expires_at TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app_id, subject, kind)
    );
CREATE TABLE app_runs (
        app_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL,
        trigger TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        subjects_json TEXT NOT NULL DEFAULT '[]',
        summary TEXT NOT NULL DEFAULT '',
        url TEXT,
        updated_at TEXT NOT NULL, by_user TEXT, progress REAL, step TEXT NOT NULL DEFAULT '', cancel_url TEXT,
        PRIMARY KEY (app_id, run_id)
    );
CREATE TABLE app_schedules (
        app_id TEXT NOT NULL,
        schedule_id TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        name TEXT NOT NULL DEFAULT '',
        cadence TEXT NOT NULL DEFAULT '',
        next_run TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        url TEXT,
        updated_at TEXT NOT NULL, subjects_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (app_id, schedule_id)
    );
CREATE TABLE app_setting_values (
        app TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        PRIMARY KEY (app, key)
    );
CREATE TABLE app_uploads (
        upload_id TEXT PRIMARY KEY,
        origin TEXT NOT NULL,
        app_id TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        sbom_json TEXT NOT NULL,
        sbom_summary_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL
    );
CREATE TABLE asset_attributes (
        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (asset_id, key)
    );
CREATE TABLE asset_imports (
        import_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        summary_json TEXT NOT NULL DEFAULT '{}',
        undo_json TEXT NOT NULL,
        undone_at TEXT,
        undone_by TEXT
    );
CREATE TABLE asset_kinds (
        kind TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
CREATE TABLE asset_relations (
        from_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        relation TEXT NOT NULL,
        to_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        origin TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (from_id, relation, to_id)
    );
CREATE TABLE asset_signals (
        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        signal_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT 'manual', source_id TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (asset_id, signal_id, origin)
    );
CREATE TABLE asset_type_seeds (
        type_id TEXT PRIMARY KEY,
        seeded_at TEXT NOT NULL
    );
CREATE TABLE asset_type_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL
    );
CREATE TABLE asset_types (
        type_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        icon TEXT NOT NULL DEFAULT '',
        parent_id TEXT,
        attributes_json TEXT NOT NULL DEFAULT '[]',
        roles_json TEXT NOT NULL DEFAULT '[]',
        children_json TEXT NOT NULL DEFAULT '[]',
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
CREATE TABLE assets (
        asset_id TEXT PRIMARY KEY,
        parent_id TEXT,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT 'manual',
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE assistant_access_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER NOT NULL DEFAULT 0,
        max_days INTEGER NOT NULL DEFAULT 30,
        updated_by TEXT,
        updated_at TEXT
    );
CREATE TABLE assistant_chat_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'done',
        steps_json TEXT NOT NULL DEFAULT '[]',
        charts_json TEXT NOT NULL DEFAULT '[]',
        refs_json TEXT NOT NULL DEFAULT '[]',
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE assistant_chats (
        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        profile TEXT NOT NULL DEFAULT '',
        ref TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    , context TEXT NOT NULL DEFAULT '', place TEXT NOT NULL DEFAULT '', kept INTEGER NOT NULL DEFAULT 1, work TEXT NOT NULL DEFAULT '', folder TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0, shared_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE assistant_evals (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        profile TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'running',
        total INTEGER NOT NULL DEFAULT 0,
        passed INTEGER NOT NULL DEFAULT 0,
        results_json TEXT NOT NULL DEFAULT '[]',
        error TEXT NOT NULL DEFAULT '',
        suite TEXT NOT NULL DEFAULT 'questions',
        skipped_json TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE assistant_tokens (
        token_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT,
        revoked_by TEXT,
        last_used_at TEXT
    );
CREATE TABLE audit_log (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        username TEXT NOT NULL,
        app_id TEXT,
        action TEXT NOT NULL,
        subject TEXT NOT NULL DEFAULT '',
        detail_json TEXT
    );
CREATE TABLE compute_limits (
        app_id TEXT PRIMARY KEY,
        timeout_seconds REAL,
        memory_mb INTEGER,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
CREATE TABLE compute_tasks (
        task_id TEXT PRIMARY KEY,
        app_id TEXT NOT NULL,
        version TEXT,
        kind TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL,
        labels_json TEXT NOT NULL DEFAULT '[]',
        run_id TEXT,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        worker_id TEXT,
        lease_until TEXT,
        timeout_seconds REAL NOT NULL,
        memory_mb INTEGER NOT NULL,
        input_bytes INTEGER NOT NULL DEFAULT 0,
        output_bytes INTEGER,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        seconds REAL,
        collected INTEGER NOT NULL DEFAULT 0
    , environment TEXT NOT NULL DEFAULT 'standard', size TEXT NOT NULL DEFAULT 'small');
CREATE TABLE compute_turns (
        app_id TEXT PRIMARY KEY,
        served_at TEXT NOT NULL
    );
CREATE TABLE compute_workers (
        worker_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        labels_json TEXT NOT NULL DEFAULT '[]',
        state TEXT NOT NULL,
        enroll_hash TEXT,
        enroll_expires_at TEXT,
        credential_hash TEXT,
        host TEXT NOT NULL DEFAULT '',
        executors_json TEXT NOT NULL DEFAULT '[]',
        stats_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        enrolled_at TEXT,
        last_seen_at TEXT,
        revoked_at TEXT
    );
CREATE TABLE conversation_members (
        conversation_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        joined_at TEXT NOT NULL,
        last_read_id INTEGER NOT NULL DEFAULT 0,
        -- A specialist preparing a reply ("thinking…"); cleared when it posts.
        busy_since TEXT,
        PRIMARY KEY(conversation_id, username),
        FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
    );
CREATE TABLE conversation_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        text TEXT NOT NULL,
        refs_json TEXT NOT NULL DEFAULT '[]',
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
    );
CREATE TABLE conversations (
        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    , group_id TEXT);
CREATE TABLE data_sources (
        source_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        settings_json TEXT NOT NULL,
        secret TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
CREATE TABLE demo_guide_links (
        name TEXT PRIMARY KEY,
        href TEXT NOT NULL
    );
CREATE TABLE demo_line (
        ticket TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        joined REAL NOT NULL,
        seen REAL NOT NULL
    );
CREATE TABLE demo_visits (
        visit TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        started REAL NOT NULL,
        ends REAL NOT NULL,
        active REAL NOT NULL
    );
CREATE TABLE derived_points (
        signal_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        value,
        PRIMARY KEY(signal_id, ts)
    ) WITHOUT ROWID;
CREATE TABLE derived_runs (
        signal_id TEXT NOT NULL,
        run_at TEXT NOT NULL,
        t_json TEXT NOT NULL,
        v_json TEXT NOT NULL,
        PRIMARY KEY(signal_id, run_at)
    ) WITHOUT ROWID;
CREATE TABLE derived_series (
        signal_id TEXT PRIMARY KEY,
        app TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'number',
        subject TEXT,
        result TEXT,
        updated_at TEXT NOT NULL
    , retention_days INTEGER, managed_by TEXT NOT NULL DEFAULT '', keep_runs INTEGER, keep_days INTEGER);
CREATE TABLE desk_app_calendar (
        app TEXT NOT NULL,
        feed TEXT NOT NULL,
        item_id TEXT NOT NULL,
        title TEXT NOT NULL,
        start TEXT NOT NULL,
        end_at TEXT,
        all_day INTEGER NOT NULL DEFAULT 0,
        audience TEXT NOT NULL,
        ref TEXT,
        url TEXT,
        detail TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (app, feed, item_id)
    );
CREATE TABLE desk_app_feeds (
        app TEXT NOT NULL,
        feed TEXT NOT NULL,
        items INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app, feed)
    );
CREATE TABLE desk_app_todos (
        app TEXT NOT NULL,
        key TEXT NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        assignee TEXT NOT NULL,
        due TEXT,
        ref TEXT,
        url TEXT,
        detail TEXT NOT NULL DEFAULT '',
        done_at TEXT,
        done_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (app, key)
    );
CREATE TABLE desk_calendars (
        calendar_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        url TEXT,
        color TEXT NOT NULL,
        events_json TEXT NOT NULL DEFAULT '[]',
        fetched_at TEXT,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
CREATE TABLE desk_checklist (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        day TEXT NOT NULL,
        title TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        routine_id INTEGER,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
CREATE TABLE desk_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        title TEXT NOT NULL,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        all_day INTEGER NOT NULL DEFAULT 0,
        repeat TEXT NOT NULL DEFAULT '',
        until TEXT,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE desk_follows (
        username TEXT NOT NULL,
        ref TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (username, ref)
    );
CREATE TABLE desk_notes (
        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        body_json TEXT NOT NULL DEFAULT '{}',
        body_text TEXT NOT NULL DEFAULT '',
        shared_json TEXT NOT NULL DEFAULT '[]',
        event_ref TEXT,
        pinned INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE desk_routines (
        routine_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        items_json TEXT NOT NULL DEFAULT '[]',
        cadence TEXT NOT NULL DEFAULT 'daily',
        days_json TEXT NOT NULL DEFAULT '[]',
        owner TEXT,
        group_id TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE desk_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE desk_todo_lists (
        list_id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner TEXT,
        group_id TEXT,
        name TEXT NOT NULL,
        color TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
CREATE TABLE desk_todos (
        todo_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        group_id TEXT,
        list_id INTEGER,
        title TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        due TEXT,
        repeat TEXT NOT NULL DEFAULT '',
        days_json TEXT NOT NULL DEFAULT '[]',
        steps_json TEXT NOT NULL DEFAULT '[]',
        my_day TEXT,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        done_by TEXT,
        action_id INTEGER,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE desk_triage (
        username TEXT NOT NULL,
        key TEXT NOT NULL,
        state TEXT NOT NULL,
        until TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (username, key)
    );
CREATE TABLE directory_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE event_catalogs (
        app TEXT PRIMARY KEY,
        events_json TEXT NOT NULL DEFAULT '[]',
        undeclared_json TEXT NOT NULL DEFAULT '[]',
        updated_at TEXT NOT NULL
    );
CREATE TABLE event_refs (
        event_id INTEGER NOT NULL REFERENCES platform_events(event_id) ON DELETE CASCADE,
        ref TEXT NOT NULL,
        PRIMARY KEY (ref, event_id)
    );
CREATE TABLE follow_up_action_history (
        entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        actor TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
CREATE TABLE follow_up_action_items (
        item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        owner TEXT,
        due_at TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        done_by TEXT,
        done_at TEXT
    );
CREATE TABLE follow_up_action_refs (
        action_id INTEGER NOT NULL REFERENCES follow_up_actions(action_id) ON DELETE CASCADE,
        ref TEXT NOT NULL,
        PRIMARY KEY (ref, action_id)
    );
CREATE TABLE follow_up_actions (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        priority TEXT NOT NULL DEFAULT 'medium',
        owner TEXT,
        due_at TEXT,
        refs_json TEXT NOT NULL DEFAULT '[]',
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    , group_id TEXT);
CREATE TABLE installation_identity (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        installation_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
CREATE TABLE installation_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        time_zone TEXT,
        updated_by TEXT,
        updated_at TEXT
    );
CREATE TABLE installed_app_sboms (
        app_id TEXT NOT NULL,
        version TEXT NOT NULL,
        sbom_json TEXT NOT NULL,
        PRIMARY KEY (app_id, version)
    );
CREATE TABLE installed_apps (
        app_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        version TEXT,
        url TEXT NOT NULL,
        origin TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL DEFAULT '',
        publisher_json TEXT,
        permissions_json TEXT,
        manifest_json TEXT,
        previous_version TEXT,
        request_id TEXT,
        request_action TEXT,
        prior_status TEXT,
        key_id TEXT,
        health_json TEXT,
        installed_by TEXT,
        installed_at TEXT,
        updated_at TEXT NOT NULL
    );
CREATE TABLE language_model (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE language_providers (
        provider_id TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE login_failures (
        key TEXT NOT NULL,
        at REAL NOT NULL
    );
CREATE TABLE mail_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE notebook_pairings (
        code_digest TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
CREATE TABLE notebook_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER NOT NULL DEFAULT 0,
        updated_by TEXT,
        updated_at TEXT
    , kit_enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE notebooks (
        notebook_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        name TEXT NOT NULL,
        content_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (username, name)
    );
CREATE TABLE notification_outbox (
        email_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        address TEXT NOT NULL,
        app_id TEXT NOT NULL,
        priority TEXT NOT NULL,
        subject TEXT NOT NULL,
        body TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        sent_at TEXT
    );
CREATE TABLE notification_resolutions (
        app_id TEXT NOT NULL,
        key TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        resolved_at TEXT NOT NULL,
        PRIMARY KEY (app_id, key)
    );
CREATE TABLE notification_threads (
        app_id TEXT NOT NULL,
        username TEXT NOT NULL,
        conversation_id INTEGER NOT NULL,
        PRIMARY KEY (app_id, username)
    );
CREATE TABLE platform_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        kind TEXT NOT NULL,
        source TEXT NOT NULL,
        subject TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT '',
        summary TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}'
    , severity TEXT NOT NULL DEFAULT '', event_key TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '');
CREATE TABLE relayed_conditions (
        app TEXT NOT NULL,
        condition_key TEXT NOT NULL,
        kind TEXT NOT NULL,
        subject TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL,
        PRIMARY KEY (app, condition_key)
    );
CREATE TABLE sdk_migrations (name TEXT PRIMARY KEY, applied_at TEXT);
CREATE TABLE signal_routes (
        tag TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        path TEXT NOT NULL DEFAULT '',
        monitored INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
CREATE TABLE specialists (
        username TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        answers INTEGER NOT NULL DEFAULT 0,
        last_answer_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL
    );
CREATE TABLE usage_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        per_minute INTEGER NOT NULL,
        concurrent INTEGER NOT NULL,
        updated_by TEXT,
        updated_at TEXT
    );
CREATE TABLE usage_slots (
        slot_id TEXT PRIMARY KEY,
        key TEXT NOT NULL,
        started REAL NOT NULL,
        finished REAL
    );
CREATE TABLE user_group_members (
        group_id TEXT NOT NULL,
        username TEXT NOT NULL,
        added_at TEXT NOT NULL,
        PRIMARY KEY (group_id, username),
        FOREIGN KEY (group_id) REFERENCES user_groups(group_id) ON DELETE CASCADE
    );
CREATE TABLE user_groups (
        group_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'team',
        description TEXT NOT NULL DEFAULT '',
        asset_id TEXT,
        coordinator TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    , parent_id TEXT, asset_scope_json TEXT);
CREATE TABLE user_preferences (
        username TEXT NOT NULL,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (username, key)
    );
CREATE TABLE watch_incidents (
        incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_key TEXT NOT NULL,
        subject TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        -- 1 when "System" posted the incident (so it posts the recovery too).
        notified INTEGER NOT NULL DEFAULT 0
    );
CREATE TABLE watch_state (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
CREATE TABLE workspace_migrations (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL,
        detail_json TEXT NOT NULL DEFAULT '{}'
    );
CREATE TABLE workspace_users (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        role TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    , password_hash TEXT, kind TEXT NOT NULL DEFAULT 'person', is_admin INTEGER NOT NULL DEFAULT 0, access_level TEXT, applications_json TEXT, profile_json TEXT, app_roles_json TEXT, tokens_valid_after INTEGER, auth_source TEXT NOT NULL DEFAULT 'local', external_id TEXT, asset_scope_json TEXT);
CREATE INDEX desk_app_calendar_start ON desk_app_calendar (start);
CREATE INDEX desk_app_todos_assignee ON desk_app_todos (assignee, done_at);
CREATE INDEX idx_app_keys_app ON app_keys(app_id);
CREATE INDEX idx_app_knowledge_ref ON app_knowledge(ref);
CREATE INDEX idx_app_result_history_recorded
        ON app_result_history(recorded_at);
CREATE INDEX idx_app_result_history_subject
        ON app_result_history(subject, at);
CREATE INDEX idx_app_results_subject ON app_results(subject, kind);
CREATE INDEX idx_app_runs_updated ON app_runs(updated_at);
CREATE INDEX idx_asset_relations_to ON asset_relations(to_id);
CREATE INDEX idx_asset_signals_signal ON asset_signals(signal_id);
CREATE INDEX idx_assets_parent ON assets(parent_id, position, name);
CREATE INDEX idx_assistant_chat_messages ON assistant_chat_messages(chat_id, message_id);
CREATE INDEX idx_assistant_chats_user ON assistant_chats(username, updated_at);
CREATE INDEX idx_assistant_tokens_user ON assistant_tokens(username);
CREATE INDEX idx_audit_log_at ON audit_log(at);
CREATE INDEX idx_compute_tasks_app ON compute_tasks(app_id, status);
CREATE INDEX idx_compute_tasks_queue
        ON compute_tasks(status, priority, created_at);
CREATE INDEX idx_compute_tasks_worker ON compute_tasks(worker_id, status);
CREATE UNIQUE INDEX idx_compute_workers_credential
        ON compute_workers(credential_hash);
CREATE INDEX idx_conversation_members_user
    ON conversation_members(username, conversation_id);
CREATE INDEX idx_conversation_messages
    ON conversation_messages(conversation_id, message_id);
CREATE INDEX idx_derived_series_app ON derived_series(app);
CREATE INDEX idx_desk_checklist_day ON desk_checklist(username, day);
CREATE UNIQUE INDEX idx_desk_checklist_routine
        ON desk_checklist(username, day, routine_id, title) WHERE routine_id IS NOT NULL;
CREATE INDEX idx_desk_events_user ON desk_events(username, start);
CREATE INDEX idx_desk_notes_owner ON desk_notes(owner, updated_at);
CREATE INDEX idx_desk_todos_group ON desk_todos(group_id, done);
CREATE INDEX idx_desk_todos_user ON desk_todos(username, done);
CREATE INDEX idx_follow_up_action_history
    ON follow_up_action_history(action_id, entry_id);
CREATE INDEX idx_follow_up_action_items
    ON follow_up_action_items(action_id, position);
CREATE INDEX idx_follow_up_actions_status
    ON follow_up_actions(status, due_at);
CREATE INDEX idx_login_failures_key ON login_failures(key, at);
CREATE INDEX idx_notebooks_user ON notebooks(username, created_at);
CREATE INDEX idx_notification_outbox_status
    ON notification_outbox(status, username);
CREATE INDEX idx_platform_events_at ON platform_events(at);
CREATE INDEX idx_platform_events_key ON platform_events(event_key, event_id);
CREATE INDEX idx_platform_events_kind ON platform_events(kind, event_id);
CREATE INDEX idx_platform_events_source_at ON platform_events(source, at);
CREATE INDEX idx_signal_routes_source ON signal_routes(source_id);
CREATE INDEX idx_usage_slots_key ON usage_slots(key, started);
CREATE INDEX idx_user_group_members_user ON user_group_members(username);
CREATE INDEX idx_watch_incidents_open
    ON watch_incidents(check_key, closed_at);
