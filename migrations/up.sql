create table if not exists connections (
    main_chan_id TEXT PRIMARY KEY,
    ping_chan_id TEXT
);

create table if not exists ping_managers (
    chan_id TEXT,
    user_id TEXT,
    PRIMARY KEY (chan_id, user_id)
);

create table if not exists pingers (
    chan_id TEXT,
    user_id TEXT,
    PRIMARY KEY (chan_id, user_id)
);