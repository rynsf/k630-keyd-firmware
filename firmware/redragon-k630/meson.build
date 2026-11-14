# Redragon K630 (single-colour, 61 keys): stock Fn layers + the keyd engine (engine/).
# Linked into smk's tree by `make firmware`; see docs/DESIGN.md for the anti-brick rules.
kb_dir = meson.current_source_dir()

keyboards += {
    'redragon-k630' : {
        'dir' : kb_dir,
        'platform' : 'sh68f90',
        'src' : files(
            'user_matrix.c',
            'user_init.c',
            'user_sleep.c',
            'kb.c',
            'hidmap.c',
            'engine/kd.c',
            'kd_config_gen.c',  # generated from keymap/rynsf.conf by `make firmware`
        ),
        'layouts' : {
            'default' : {
                'dir' : kb_dir / 'layouts/default',
                'src' : files('layouts/default/layout.c'),
            },
        },
        'options' : {
            'vendor_id' : '0x258a',
            'product_id' : '0x002a',  # the stock ID: sinowisp -d redragon-k630-norgb keeps working
            'nvm' : 'none',           # never write flash
            'watchdog_enable' : '1',
        },
    },
}
