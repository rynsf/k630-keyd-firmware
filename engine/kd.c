/*
 * Port of keyd v2.6.0 src/keyboard.c (© 2019 Raheman Vaiya, MIT licence) restricted to the
 * actions kd_config.h describes. Structure and names follow the original so the two can be
 * read side by side; every behavioural difference is listed here:
 *
 *  - No chords, macros, commands, repeat, swap, timeout(), overloadi, scroll, composite layers
 *    (tools/keyd-oracle/export.c refuses configs that use them).
 *  - keyd's recursion (handle_pending_overload -> kbd_process_events on a stack copy of the
 *    queue) is replaced by an explicit frame stack in XRAM that runs the same events in the
 *    same order, with the same per-call timeout bookkeeping.
 *  - Where keyd would assert (queue / cache / timeout list overflow), events are dropped and
 *    kd_overflow is incremented.
 *  - Time comparisons are wrap-safe (signed difference); identical to keyd's for times that
 *    do not wrap.
 *  - keystate is a bitmap.
 */
#include "kd.h"
#include "kd_config.h"

#ifdef __SDCC
#define KD_XDATA __xdata
#else
#define KD_XDATA
#endif

#define CACHE_SIZE 16
#define QUEUE_SIZE 32
#define MAX_TIMEOUTS 16
#define MAX_FRAMES 6
#define MAX_LAYERS 32

/* keys.h */
#define KEYD_LEFTCTRL 29
#define KEYD_LEFTSHIFT 42
#define KEYD_LEFTALT 56
#define KEYD_RIGHTALT 100
#define KEYD_LEFTMETA 125
#define KEYD_NOOP 195
#define KEYD_EXTERNAL_MOUSE_BUTTON 196

#define MOD_ALT_GR 0x10
#define MOD_CTRL 0x8
#define MOD_SHIFT 0x4
#define MOD_SUPER 0x2
#define MOD_ALT 0x1

#define TIME_GE(a, b) ((int32_t)((uint32_t)(a) - (uint32_t)(b)) >= 0)
#define TIME_GT(a, b) ((int32_t)((uint32_t)(a) - (uint32_t)(b)) > 0)

/* keys.c: modifiers[] — order matters (set_mods emits in this order). */
static const KD_CODE uint8_t mod_mask[5] = {MOD_ALT, MOD_ALT_GR, MOD_SHIFT, MOD_SUPER, MOD_CTRL};
static const KD_CODE uint8_t mod_key[5] = {KEYD_LEFTALT, KEYD_RIGHTALT, KEYD_LEFTSHIFT,
					   KEYD_LEFTMETA, KEYD_LEFTCTRL};

struct desc {
	uint8_t op;
	uint8_t a0;
	uint8_t a1;
	uint16_t a2;
};

struct key_event {
	uint8_t code;
	uint8_t pressed;
	kd_time_t timestamp;
};

struct cache_entry {
	uint8_t code;
	struct desc d;
	int8_t dl;
	int8_t layer;
};

uint8_t kd_overflow;
uint8_t kd_peak_frames;

static KD_XDATA struct {
	struct cache_entry cache[CACHE_SIZE];

	uint8_t last_pressed_output_code;
	uint8_t last_pressed_code;
	uint8_t oneshot_latch;
	uint8_t inhibit_modifier_guard;

	kd_time_t oneshot_timeout;
	kd_time_t overload_start_time;
	kd_time_t last_simple_key_time;

	kd_time_t timeouts[MAX_TIMEOUTS];
	uint8_t nr_timeouts;

	struct {
		uint8_t code;
		int8_t dl;
		kd_time_t expiration;
		uint8_t resolve_on_interrupt;
		struct key_event queue[QUEUE_SIZE];
		uint8_t queue_sz;
		struct desc action1;
		struct desc action2;
	} pending_overload;

	struct {
		int32_t activation_time;
		uint8_t active;
		uint8_t toggled;
		uint8_t oneshot_depth;
	} layer_state[MAX_LAYERS];

	uint8_t keystate[32];
	int32_t clock; /* get_time() */
} kbd;

/*
 * Frame stack replacing the recursion in kbd_process_events / handle_pending_overload.
 * A frame is one kbd_process_events() call: its event list, cursor and the local
 * timeout/timeout_ts. `waiting` is set while a nested flush (child frame) runs on behalf of
 * the event at the cursor; when the child finishes, the parent finishes that process_event
 * call (calculate_main_loop_timeout) exactly where keyd would after returning.
 */
static KD_XDATA struct frame {
	struct key_event ev[QUEUE_SIZE];
	uint8_t n;
	uint8_t i;
	kd_time_t timeout;
	kd_time_t timeout_ts;
	uint8_t waiting;
	uint8_t wait_is_timeout;
	kd_time_t wait_time;
} frames[MAX_FRAMES];
static uint8_t nr_frames;
static uint8_t flush_requested;

/* ---- helpers ------------------------------------------------------------------------- */

static void load_desc(struct desc *d, const KD_CODE struct kd_desc *s)
{
	d->op = s->op;
	d->a0 = s->a0;
	d->a1 = s->a1;
	d->a2 = s->a2;
}

static uint8_t ks_get(uint8_t code)
{
	return (kbd.keystate[code >> 3] >> (code & 7)) & 1;
}

static void ks_set(uint8_t code, uint8_t v)
{
	if (v)
		kbd.keystate[code >> 3] |= (uint8_t)(1u << (code & 7));
	else
		kbd.keystate[code >> 3] &= (uint8_t)~(1u << (code & 7));
}

static int32_t get_time(void)
{
	return kbd.clock++;
}

static int8_t cache_set(uint8_t code, const struct cache_entry *ent)
{
	uint8_t i;
	int8_t slot = -1;

	for (i = 0; i < CACHE_SIZE; i++)
		if (kbd.cache[i].code == code) {
			slot = (int8_t)i;
			break;
		} else if (!kbd.cache[i].code) {
			slot = (int8_t)i;
		}

	if (slot == -1)
		return -1;

	if (ent == 0) {
		kbd.cache[slot].code = 0;
	} else {
		kbd.cache[slot] = *ent;
		kbd.cache[slot].code = code;
	}
	return 0;
}

static struct cache_entry KD_XDATA *cache_get(uint8_t code)
{
	uint8_t i;
	for (i = 0; i < CACHE_SIZE; i++)
		if (kbd.cache[i].code == code)
			return &kbd.cache[i];
	return 0;
}

static void reset_keystate(void)
{
	uint16_t i;
	for (i = 0; i < 256; i++)
		if (ks_get((uint8_t)i)) {
			kd_output((uint8_t)i, 0);
			ks_set((uint8_t)i, 0);
		}
}

static void send_key(uint8_t code, uint8_t pressed)
{
	if (code == KEYD_NOOP || code == KEYD_EXTERNAL_MOUSE_BUTTON)
		return;

	if (pressed)
		kbd.last_pressed_output_code = code;

	if (ks_get(code) != pressed) {
		ks_set(code, pressed);
		kd_output(code, pressed);
	}
}

static void clear_mod(uint8_t code)
{
	uint8_t guard = (kbd.last_pressed_output_code == code &&
			 (code == KEYD_LEFTMETA || code == KEYD_LEFTALT || code == KEYD_RIGHTALT)) &&
			!kbd.inhibit_modifier_guard && !kd_cfg.disable_modifier_guard;

	if (guard && !ks_get(KEYD_LEFTCTRL)) {
		send_key(KEYD_LEFTCTRL, 1);
		send_key(code, 0);
		send_key(KEYD_LEFTCTRL, 0);
	} else {
		send_key(code, 0);
	}
}

static void set_mods(uint8_t mods)
{
	uint8_t i;
	for (i = 0; i < 5; i++) {
		uint8_t mask = mod_mask[i];
		uint8_t code = mod_key[i];

		if (mask & mods) {
			if (!ks_get(code))
				send_key(code, 1);
		} else {
			if (ks_get(code))
				clear_mod(code);
		}
	}
}

static uint8_t update_mods(int8_t excluded_layer_idx, uint8_t mods)
{
	uint8_t i;
	for (i = 0; i < kd_cfg.nr_layers; i++) {
		if (!kbd.layer_state[i].active)
			continue;
		if ((int8_t)i != excluded_layer_idx)
			mods |= kd_layers[i].mods;
	}
	set_mods(mods);
	return mods;
}

static uint8_t layer_lookup(uint8_t layer, uint8_t code, struct desc *d)
{
	const KD_CODE struct kd_layer *l = &kd_layers[layer];
	uint16_t j;
	for (j = l->first; j < (uint16_t)(l->first + l->n); j++) {
		if (kd_binds[j].code == code) {
			load_desc(d, &kd_binds[j].d);
			return 1;
		}
		if (kd_binds[j].code > code)
			break;
	}
	return 0;
}

static void lookup_descriptor(uint8_t code, struct desc *d, int8_t *dl)
{
	uint8_t i;
	int32_t maxts = 0;
	struct desc tmp;

	d->op = 0;

	for (i = 0; i < kd_cfg.nr_layers; i++) {
		if (kbd.layer_state[i].active) {
			int32_t activation_time = kbd.layer_state[i].activation_time;
			if (layer_lookup(i, code, &tmp) && activation_time >= maxts) {
				maxts = activation_time;
				*d = tmp;
				*dl = (int8_t)i;
			}
		}
	}

	if (!d->op) {
		d->op = KD_OP_KEYSEQUENCE;
		d->a0 = code;
		d->a1 = 0;
		*dl = 0;
	}
}

static void deactivate_layer(uint8_t idx)
{
	if (kbd.layer_state[idx].active)
		kbd.layer_state[idx].active--;
}

static void activate_layer(uint8_t code, uint8_t idx)
{
	struct cache_entry KD_XDATA *ce;

	kbd.layer_state[idx].activation_time = get_time();
	kbd.layer_state[idx].active++;

	if ((ce = cache_get(code)))
		ce->layer = (int8_t)idx;
}

static void clear_oneshot(void)
{
	uint8_t i;
	for (i = 0; i < kd_cfg.nr_layers; i++)
		while (kbd.layer_state[i].oneshot_depth) {
			deactivate_layer(i);
			kbd.layer_state[i].oneshot_depth--;
		}
	kbd.oneshot_latch = 0;
	kbd.oneshot_timeout = 0;
}

static void clear(void)
{
	uint8_t i;
	clear_oneshot();
	for (i = 1; i < kd_cfg.nr_layers; i++) {
		if (kd_layers[i].type != KD_LT_LAYOUT) {
			if (kbd.layer_state[i].toggled) {
				kbd.layer_state[i].toggled = 0;
				deactivate_layer(i);
			}
		}
	}
	reset_keystate();
}

static void setlayout(uint8_t idx)
{
	uint8_t i;
	clear();
	for (i = 1; i < kd_cfg.nr_layers; i++)
		if (kd_layers[i].type == KD_LT_LAYOUT)
			kbd.layer_state[i].active = 0;

	if (idx != 0) {
		kbd.layer_state[idx].activation_time = 1;
		kbd.layer_state[idx].active = 1;
	}
}

static void schedule_timeout(kd_time_t timeout)
{
	if (kbd.nr_timeouts >= MAX_TIMEOUTS) {
		kd_overflow++;
		return;
	}
	kbd.timeouts[kbd.nr_timeouts++] = timeout;
}

static kd_time_t calculate_main_loop_timeout(kd_time_t time)
{
	uint8_t i, n = 0;
	kd_time_t timeout = 0;
	uint8_t have = 0;

	for (i = 0; i < kbd.nr_timeouts; i++)
		if (TIME_GT(kbd.timeouts[i], time)) {
			if (!have || TIME_GT(timeout, kbd.timeouts[i])) {
				timeout = kbd.timeouts[i];
				have = 1;
			}
			kbd.timeouts[n++] = kbd.timeouts[i];
		}

	kbd.nr_timeouts = n;
	return have ? timeout - time : 0;
}

static void process_descriptor(uint8_t code, const struct desc *d, int8_t dl, uint8_t pressed,
			       kd_time_t time);

static void process_descriptor(uint8_t code, const struct desc *d, int8_t dl, uint8_t pressed,
			       kd_time_t time)
{
	uint8_t idx, mods, new_code;
	struct desc action;

	switch (d->op) {
	case KD_OP_KEYSEQUENCE:
		new_code = d->a0;
		mods = d->a1;
		if (pressed) {
			if (ks_get(new_code))
				send_key(new_code, 0);

			update_mods(dl, mods);

			send_key(new_code, 1);
			clear_oneshot();
		} else {
			send_key(new_code, 0);
			update_mods(-1, 0);
		}

		if (!mods || mods == MOD_SHIFT)
			kbd.last_simple_key_time = time;
		break;

	case KD_OP_OVERLOAD_TIMEOUT_TAP:
	case KD_OP_OVERLOAD_TIMEOUT:
		if (pressed) {
			kbd.pending_overload.code = code;
			kbd.pending_overload.resolve_on_interrupt = d->op == KD_OP_OVERLOAD_TIMEOUT_TAP;
			kbd.pending_overload.dl = dl;
			load_desc(&kbd.pending_overload.action1, &kd_descs[d->a1]);
			kbd.pending_overload.action2.op = KD_OP_LAYER;
			kbd.pending_overload.action2.a0 = d->a0;
			kbd.pending_overload.action2.a1 = 0;
			kbd.pending_overload.action2.a2 = 0;
			kbd.pending_overload.expiration = time + d->a2;
			schedule_timeout(kbd.pending_overload.expiration);
		}
		break;

	case KD_OP_LAYOUT:
		if (pressed)
			setlayout(d->a0);
		break;

	case KD_OP_LAYER:
		idx = d->a0;
		if (pressed)
			activate_layer(code, idx);
		else
			deactivate_layer(idx);

		if (kbd.last_pressed_code == code) {
			kbd.inhibit_modifier_guard = 1;
			update_mods(-1, 0);
			kbd.inhibit_modifier_guard = 0;
		} else {
			update_mods(-1, 0);
		}
		break;

	case KD_OP_CLEAR:
		if (pressed)
			clear();
		break;

	case KD_OP_OVERLOAD:
		idx = d->a0;
		load_desc(&action, &kd_descs[d->a1]);

		if (pressed) {
			kbd.overload_start_time = time;
			activate_layer(code, idx);
			update_mods(-1, 0);
		} else {
			deactivate_layer(idx);
			update_mods(-1, 0);

			if (kbd.last_pressed_code == code &&
			    (!kd_cfg.overload_tap_timeout ||
			     ((time - kbd.overload_start_time) < (kd_time_t)kd_cfg.overload_tap_timeout))) {
				process_descriptor(code, &action, dl, 1, time);
				process_descriptor(code, &action, dl, 0, time);
			}
		}
		break;

	case KD_OP_ONESHOT:
		idx = d->a0;
		if (pressed) {
			activate_layer(code, idx);
			update_mods(dl, 0);
			kbd.oneshot_latch = 1;
		} else {
			if (kbd.oneshot_latch) {
				kbd.layer_state[idx].oneshot_depth++;
				if (kd_cfg.oneshot_timeout) {
					kbd.oneshot_timeout = time + kd_cfg.oneshot_timeout;
					schedule_timeout(kbd.oneshot_timeout);
				}
			} else {
				deactivate_layer(idx);
				update_mods(-1, 0);
			}
		}
		break;

	case KD_OP_TOGGLE:
		idx = d->a0;
		if (pressed) {
			kbd.layer_state[idx].toggled = !kbd.layer_state[idx].toggled;
			if (kbd.layer_state[idx].toggled)
				activate_layer(code, idx);
			else
				deactivate_layer(idx);
			update_mods(-1, 0);
			clear_oneshot();
		}
		break;
	}

	if (pressed)
		kbd.last_pressed_code = code;
}

/* Pushes a frame with the queued events; the driver loop runs it. */
static void push_flush(const struct key_event KD_XDATA *queue, uint8_t queue_sz)
{
	struct frame KD_XDATA *f;
	uint8_t i;

	if (nr_frames >= MAX_FRAMES) {
		kd_overflow++;
		return;
	}
	f = &frames[nr_frames++];
	if (nr_frames > kd_peak_frames)
		kd_peak_frames = nr_frames;
	for (i = 0; i < queue_sz; i++)
		f->ev[i] = queue[i];
	f->n = queue_sz;
	f->i = 0;
	f->timeout = 0;
	f->timeout_ts = 0;
	f->waiting = 0;
	flush_requested = 1;
}

static uint8_t handle_pending_overload(uint8_t code, uint8_t pressed, kd_time_t time)
{
	struct desc action;

	if (!kbd.pending_overload.code)
		return 0;

	if (code) {
		struct key_event KD_XDATA *ev;

		if (!pressed) {
			uint8_t i;
			uint8_t found = 0;

			for (i = 0; i < kbd.pending_overload.queue_sz; i++)
				if (kbd.pending_overload.queue[i].code == code)
					found = 1;

			/* Propagate key up events for keys which were struck before the pending key. */
			if (!found && code != kbd.pending_overload.code)
				return 0;
		}

		if (kbd.pending_overload.queue_sz >= QUEUE_SIZE) {
			kd_overflow++;
			return 1;
		}
		ev = &kbd.pending_overload.queue[kbd.pending_overload.queue_sz];
		ev->code = code;
		ev->pressed = pressed;
		ev->timestamp = time;
		kbd.pending_overload.queue_sz++;
	}

	if (TIME_GE(time, kbd.pending_overload.expiration))
		action = kbd.pending_overload.action2;
	else if (code == kbd.pending_overload.code)
		action = kbd.pending_overload.action1;
	else if (kbd.pending_overload.resolve_on_interrupt && !pressed)
		action = kbd.pending_overload.action2;
	else
		action.op = 0;

	if (action.op) {
		uint8_t pcode = kbd.pending_overload.code;
		int8_t dl = kbd.pending_overload.dl;
		struct cache_entry ce;

		kbd.pending_overload.code = 0;

		ce.code = 0;
		ce.d = action;
		ce.dl = dl;
		ce.layer = 0;
		cache_set(pcode, &ce);
		process_descriptor(pcode, &action, dl, 1, time);

		/* Flush queued events (keyd: kbd_process_events on a stack copy). */
		push_flush(kbd.pending_overload.queue, kbd.pending_overload.queue_sz);
		kbd.pending_overload.queue_sz = 0;
	}

	return 1;
}

/*
 * process_event up to (not including) the final calculate_main_loop_timeout. Returns 1 if a
 * nested flush frame was pushed; the caller finishes the call once that frame has run.
 */
static uint8_t process_event_begin(uint8_t code, uint8_t pressed, kd_time_t time)
{
	flush_requested = 0;

	if (handle_pending_overload(code, pressed, time))
		return flush_requested;

	if (kbd.oneshot_timeout && TIME_GE(time, kbd.oneshot_timeout)) {
		clear_oneshot();
		update_mods(-1, 0);
	}

	if (code) {
		struct desc d;
		int8_t dl = 0;

		if (pressed) {
			struct cache_entry ce;

			if (cache_get(code))
				return 0;

			lookup_descriptor(code, &d, &dl);

			ce.code = 0;
			ce.d = d;
			ce.dl = dl;
			ce.layer = 0;
			if (cache_set(code, &ce))
				return 0;
		} else {
			struct cache_entry KD_XDATA *ce;
			if (!(ce = cache_get(code)))
				return 0;

			d = ce->d;
			dl = ce->dl;
			cache_set(code, 0);
		}

		process_descriptor(code, &d, dl, pressed, time);
	}
	return 0;
}

/* ---- kbd_process_events, iteratively ------------------------------------------------ */

static void frame_finish_call(struct frame KD_XDATA *f, uint8_t was_timeout, kd_time_t time)
{
	kd_time_t t = calculate_main_loop_timeout(time);
	f->timeout = t;
	if (was_timeout) {
		f->timeout_ts = f->timeout_ts + t;
	} else {
		f->timeout_ts = time + t;
		f->i++;
	}
}

kd_time_t kd_event(uint8_t code, uint8_t pressed, kd_time_t t)
{
	kd_time_t result = 0;

	nr_frames = 1;
	frames[0].ev[0].code = code;
	frames[0].ev[0].pressed = pressed;
	frames[0].ev[0].timestamp = t;
	frames[0].n = 1;
	frames[0].i = 0;
	frames[0].timeout = 0;
	frames[0].timeout_ts = 0;
	frames[0].waiting = 0;

	while (nr_frames) {
		struct frame KD_XDATA *f = &frames[nr_frames - 1];
		const struct key_event KD_XDATA *ev;
		uint8_t is_timeout;
		kd_time_t time;

		if (f->waiting) {
			f->waiting = 0;
			frame_finish_call(f, f->wait_is_timeout, f->wait_time);
			continue;
		}

		if (f->i == f->n) {
			result = f->timeout;
			nr_frames--;
			continue;
		}

		ev = &f->ev[f->i];
		if (f->timeout > 0 && TIME_GE(ev->timestamp, f->timeout_ts)) {
			is_timeout = 1;
			time = f->timeout_ts;
			code = 0;
			pressed = 0;
		} else {
			is_timeout = 0;
			time = ev->timestamp;
			code = ev->code;
			pressed = ev->pressed;
		}

		if (process_event_begin(code, pressed, time)) {
			/* a child frame was pushed above f; finish this call when it is done */
			f->waiting = 1;
			f->wait_is_timeout = is_timeout;
			f->wait_time = time;
		} else {
			frame_finish_call(f, is_timeout, time);
		}
	}

	return result;
}

void kd_init(void)
{
	uint16_t i;
	uint8_t KD_XDATA *p = (uint8_t KD_XDATA *)&kbd;

	for (i = 0; i < sizeof(kbd); i++)
		p[i] = 0;
	kbd.clock = 1;
	nr_frames = 0;
	kd_overflow = 0;

	kbd.layer_state[0].active = 1;
	kbd.layer_state[0].activation_time = 0;

	if (kd_cfg.default_layout) {
		kbd.layer_state[kd_cfg.default_layout].active = 1;
		kbd.layer_state[kd_cfg.default_layout].activation_time = 1;
	}
}
