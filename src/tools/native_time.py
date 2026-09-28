"""v3 native axes and paid motion anchor; no resampling or model execution."""
import numpy as np


def time_axis(value, *, history=False):
    times=np.asarray(value,dtype=float)
    if (times.ndim!=1 or not len(times) or not np.isfinite(times).all()
        or np.any(np.diff(times)<=0) or (history and (times[-1]!=0 or times[0]>0))
        or (not history and times[0]<=0)):
        raise ValueError('ordered native time axis required')
    return times


def check_binding(binding):
    if (not isinstance(binding,dict) or set(binding)!={'version','decision_time','axes','origin','time_binding'}
        or binding['version']!='ego_actor_time_v1' or binding['axes']!='x_forward_y_left'
        or binding['origin']!='ego_actor' or type(binding['decision_time']) not in (int,float)
        or not np.isfinite(binding['decision_time']) or not isinstance(binding['time_binding'],str)
        or not binding['time_binding'].strip()):raise ValueError('invalid native frame/time binding')


def motion(states,valid,times):
    states=np.asarray(states,dtype=float);times=np.asarray(times,dtype=float)
    indices=np.flatnonzero(valid);velocity=np.zeros(2);support=[]
    if len(indices)>=2:
        a,b=indices[-2:];velocity=(states[b,:2]-states[a,:2])/(times[b]-times[a]);support=[float(times[a]),float(times[b])]
    return dict(velocity=velocity.tolist(),valid=len(indices)>=2,support_times=support,
                source='causal_tracking_state_motion_proxy')


def forecast_at(window,forecast,times):
    from tools.task_spec import validate_prediction
    means,_,_=validate_prediction(window,forecast,native=True)
    axis=time_axis(forecast['forecast_times']);times=time_axis(times)
    if times[-1]>axis[-1]:raise ValueError('native forecast does not cover request; no extrapolation')
    result=np.empty((len(means),means.shape[1],len(times),2))
    axis=np.r_[0.,axis]
    for i in range(len(means)):
        for m in range(means.shape[1]):
            xy=np.vstack([window['states'][i,-1,:2],means[i,m]])
            for d in range(2):result[i,m,:,d]=np.interp(times,axis,xy[:,d])
    return result
