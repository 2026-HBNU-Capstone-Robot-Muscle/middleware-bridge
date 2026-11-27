"""Shared finger initialization, current limits and pose checks."""
import time
from .core import Fault, finite, states_by_id


AGE=.1
INITIAL_TOLERANCE_TICK=10
# User-requested +30 ticks on measured upper-position tolerance (previously 3).
POSITION_UPPER_MARGIN_TICK=33
# Requested operating limit; EEPROM is restored after confirmed torque OFF.
CURRENT_LIMIT_MA=1000
CURRENT_TRANSIENT_MARGIN_MA=50


class Guard:
    def __init__(self,cfg,rows,inventory,initializing=False):
        self.temperature_stop={m["id"]:m["temperature_limit_c"]-1 for m in inventory}
        self.initializing=initializing
        self.current_stop={m["id"]:min(CURRENT_LIMIT_MA,m["current_limit_ma"]) for m in inventory}
        self.current_over_count={i:0 for i in self.current_stop}
        self.current_sample_start={i:None for i in self.current_stop}
        self.ends={m['id']:(m['provisional_close_tick'],m['initial_position_tick']) for m in cfg['motors']}
        self.previous={r['id']:r['position_tick'] for r in rows}
        self.upper={i:max(self.previous[i],hi) for i,(lo,hi) in self.ends.items()}
        self.failed=False
        for i,(lo,hi) in self.ends.items():
            if not 0<=lo<hi<=4095:
                raise Fault(f'ID{i}: invalid configured position endpoints')
            # During initialization accept any valid single-turn encoder value;
            # the operator may have manually positioned the hand outside the
            # provisional policy range. Check the policy range after homing.
            position=self.previous[i]
            if not 0<=position<=4095 or (not initializing and not lo<=position<=hi+64):
                raise Fault(f'ID{i}: outside provisional starting envelope')

    def check(self,rows):
        try:
            if self.failed: raise Fault('Latched fault')
            by=states_by_id(rows,time.monotonic(),AGE)
            now=time.monotonic()
            for i,r in by.items():
                lo,_=self.ends[i]
                position=r['position_tick']
                if self.initializing:
                    if not 0<=position<=4095: raise Fault(f'ID{i}: invalid single-turn position')
                elif not lo-3<=position<=self.upper[i]+POSITION_UPPER_MARGIN_TICK:
                    raise Fault(f'ID{i}: position limit: actual={position}, allowed={lo-3}..{self.upper[i]+POSITION_UPPER_MARGIN_TICK}')
                current=abs(r['current_ma'])
                limit=self.current_stop[i]
                if self.initializing and current>limit:
                    raise Fault(f'ID{i}: initialization current {current}mA exceeds {limit}mA')
                if current>limit+CURRENT_TRANSIENT_MARGIN_MA:
                    raise Fault(f'ID{i}: current {current}mA exceeds immediate stop {limit+CURRENT_TRANSIENT_MARGIN_MA}mA')
                # Guard.check can run twice on one read. Count each fresh read once.
                sample=r['sample_start_s']
                if sample!=self.current_sample_start[i]:
                    self.current_sample_start[i]=sample
                    self.current_over_count[i]=self.current_over_count[i]+1 if current>limit else 0
                if self.current_over_count[i]>=2:
                    raise Fault(f'ID{i}: current above {limit}mA in two consecutive reads (latest {current}mA)')
                if r['temperature_c']>=self.temperature_stop[i]:
                    raise Fault(f'ID{i}: temperature approaching configured device limit')
                # No arbitrary measured-speed or timed 600mA stall cutoff.
                # Device overload detection is checked by command_sync before goals.
            return by
        except BaseException:
            self.failed=True
            raise

    def targets(self,raw):
        if self.failed: raise Fault('Latched fault')
        if set(raw)!={1,2,3,4}: raise Fault('Incomplete action targets')
        out={}
        for i,(lo,hi) in self.ends.items():
            desired=max(lo,min(hi,finite(raw[i])))
            # Preserve the policy's absolute goal; only endpoint clipping and
            # encoder quantization are applied. Motor-internal profile remains.
            out[i]=max(lo,min(hi,round(desired)))
        self.previous=out
        return out


def initial_pose_ready(cfg,rows):
    by=states_by_id(rows,time.monotonic(),AGE)
    return all(abs(by[m['id']]['position_tick']-m['initial_position_tick'])<=INITIAL_TOLERANCE_TICK
               and abs(by[m['id']]['velocity_tick_s'])<=32 for m in cfg['motors'])


def move_to_initial(bus,cfg,guard,emit,timeout=15.,clock=time.monotonic,sleep=time.sleep,check=lambda:None):
    targets={m['id']:m['initial_position_tick'] for m in cfg['motors']}
    check()
    rows=bus.read_diagnostic(); guard.check(rows)
    emit({'type':'initial_move_attempt','targets':targets,'rows':rows})
    bus.command_sync(targets,rows,AGE)
    began=clock(); settled=None
    while clock()-began<timeout:
        check()
        rows=bus.read_diagnostic()
        emit({'type':'initial_move_state','rows':rows})
        guard.check(rows)
        errors=bus.read_register_sync(70,1)
        if any(errors.values()): raise Fault(f'Hardware error during initial move: {errors}')
        now=clock()
        reached=initial_pose_ready(cfg,rows)
        settled=(now if settled is None else settled) if reached else None
        if settled is not None and now-settled>=.3:
            emit({'type':'initial_pose_reached','targets':targets,'rows':rows})
            return rows
        sleep(.02)
    raise Fault('Initial position not reached within 15s; policy was not started')


def preflight(inv):
    if len(inv)!=4 or {m['id'] for m in inv}!={1,2,3,4}: raise Fault('Incomplete inventory')
    for m in inv:
        if m['model_number']!=1200 or m['mode']!=5 or m['drive_mode']!=0:
            raise Fault('Requires XL330-M288, mode5, drive0')
        if m['torque'] or m['watchdog'] or m['hardware_error']:
            raise Fault(f"ID{m['id']}: startup requires torque=0, watchdog=0, hardware_error=0; actual torque={m['torque']}, watchdog={m['watchdog']}, hardware_error=0x{m['hardware_error']:02X}")
        if m['secondary_id']!=255 or m['status_return_level']!=2:
            raise Fault('Secondary ID must be disabled; status return2 required')
        if not 1<m['temperature_limit_c']<=100 or m['shutdown_mask'] & 0x24 != 0x24:
            raise Fault('Device overheat and overload shutdown must be enabled; invalid temperature setting')
        if not 0<m['current_limit_ma']<=1750: raise Fault('Invalid XL330 EEPROM current limit')
        if abs(m['goal_current_raw'])>m['current_limit_ma']: raise Fault('Existing goal current exceeds EEPROM limit')


def set_trial_current(bus, inventory, restore, emit):
    """Set 1000 mA with all motors torque-off; record restoration before each write."""
    for motor in inventory:
        i=motor['id']
        if bus.read_int(i,64,1)!=0:
            raise Fault(f'ID {i}: torque must be off before changing current limit')
        restore[i]=(motor['current_limit_ma'],motor['goal_current_raw'])
        if motor['current_limit_ma']!=CURRENT_LIMIT_MA:
            bus.write_checked(i,38,CURRENT_LIMIT_MA,2)
        bus.write_checked(i,102,CURRENT_LIMIT_MA,2)
        emit({'type':'current_limit_set','id':i,'current_limit_ma':CURRENT_LIMIT_MA,
              'goal_current_ma':CURRENT_LIMIT_MA,'previous_limit_ma':restore[i][0],
              'previous_goal_ma':restore[i][1]})
    # Do not overwrite original inventory: it is needed for gain/profile restoration.
    return [dict(m,current_limit_ma=CURRENT_LIMIT_MA,goal_current_raw=CURRENT_LIMIT_MA)
            for m in inventory]


def restore_trial_current(bus, restore, emit):
    """Restore EEPROM and signed goal only after torque-off has been confirmed."""
    errors=[]
    for i,(limit,goal) in restore.items():
        try:
            if bus.read_int(i,64,1)!=0: raise Fault('torque OFF not confirmed')
            # Zero the RAM goal before lowering the EEPROM limit.
            bus.write_checked(i,102,0,2)
            if bus.read_int(i,38,2)!=limit: bus.write_checked(i,38,limit,2)
            bus.write_checked(i,102,goal & 0xffff,2)
            emit({'type':'current_limit_restored','id':i,'current_limit_ma':limit,'goal_current_ma':goal})
        except Exception as exc:
            errors.append(f'ID {i}: current restoration failed: {exc}')
            emit({'type':'current_restore_failed','id':i,'error':str(exc)})
    return errors


def initial_setup(bus,cfg,inv,rows,guard,args,effective_i,gain_restore,i_restore,profile_restore,emit,check=lambda:None):
    # In mode 5, Goal Current is a current limit. Keep it at zero while
    # enabling torque and replacing any old goal with the configured open pose.
    # No goal is written while torque is OFF; no present-position match is needed.
    targets={m['id']:m['initial_position_tick'] for m in cfg['motors']}
    if set(targets)!={1,2,3,4} or any(type(v) is not int or not 0<=v<=4095 for v in targets.values()):
        raise Fault('Invalid initial open targets')
    bus.armed_ids=[1,2,3,4]
    for m in inv:
        check()
        i=m['id']
        if bus.read_int(i,64,1)!=0: raise Fault(f'ID {i}: initialization requires torque OFF')
        gain_restore[i]=m['position_p_gain']
        profile_restore[i]=(m['profile_velocity_raw'],m['profile_acceleration_raw'])
        bus.write_checked(i,102,0,2)
        bus.write_checked(i,84,500,2)
        bus.write_checked(i,112,20,4)
        bus.write_checked(i,108,10,4)
    fresh=bus.read_diagnostic(); guard.check(fresh)
    for i in range(1,5):
        check()
        bus.write_checked(i,98,25,1)
    for i in range(1,5):
        check()
        if bus.read_int(i,102,2)!=0: raise Fault(f'ID {i}: initial current limit must remain zero')
        emit({'type':'enable_attempt','id':i,'goal_current_ma':0})
        bus.write_checked(i,64,1,1)
        if bus.read_int(i,102,2)!=0: raise Fault(f'ID {i}: initial current limit changed during enable')
    check()
    fresh=bus.read_diagnostic(); guard.check(fresh)
    # A stale goal may be arbitrarily far from open3. Replace it under zero
    # current and require an exact goal readback before allowing drive current.
    bus.command_sync(targets,fresh,AGE)
    emit({'type':'initial_open_prepared','targets':targets,'goal_current_ma':0})
    for i in range(1,5):
        check()
        if bus.read_int(i,64,1)!=1: raise Fault(f'ID {i}: torque lost before initial move')
        if bus.read_int(i,102,2)!=0: raise Fault(f'ID {i}: initial current limit changed before move')
        if bus.read_int(i,116,4)!=targets[i]: raise Fault(f'ID {i}: initial open goal changed before move')
        bus.write_checked(i,102,CURRENT_LIMIT_MA,2)
    print('Moving to saved initial pose...')
    try:
        rows=move_to_initial(bus,cfg,guard,emit,check=check)
    except (InterruptedError,TimeoutError):
        raise
    except Exception as exc:
        raise Fault(f'finger initial move: {type(exc).__name__}: {exc}') from exc
    for m in inv:
        check()
        i=m['id']
        bus.write_checked(i,84,args.position_p if args.position_p is not None else m['position_p_gain'],2)
        if effective_i is not None:
            i_restore[i]=m['position_i_gain']
            bus.write_checked(i,82,effective_i,2)
        bus.write_checked(i,112,args.profile_velocity,4)
        bus.write_checked(i,108,args.profile_acceleration,4)
    rows=bus.read_diagnostic()
    if not initial_pose_ready(cfg,rows):
        raise Fault('Initial pose changed during gain setup; policy was not started')
    guard=Guard(cfg,rows,inv); guard.check(rows)
    return guard
