"""Run original CPU raster function on known geometry, no network/model calls."""
import ast,json,sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'.worktrees/codriving-pf-bev/src'))
from planning.codriving_pf_bev import rasterize_pf
source=Path('/root/autodl-tmp/toolv2x_backbone_research_2026_09_19/V2Xverse_official/opencood/utils/occ_render.py')
node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='turn_traffic_into_map')
namespace={'np':np,'plt':plt};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
records=[]
for x,y,yaw in [(10.,0.,0.),(10.,4.,0.),(-5.,-4.,.7),(35.,0.,.3)]:
 box=np.array([x,y,4.,2.,yaw]);c,s=np.cos(yaw),np.sin(yaw);corners=np.array([[-2,-1],[2,-1],[2,1],[-2,1]])@np.array([[c,s],[-s,c]])+box[:2]
 # Upstream renderer axes are right/forward; canonical adapter uses forward/left.
 native=np.stack([-corners[:,1],corners[:,0]],axis=-1)
 official=namespace['turn_traffic_into_map'](native[None],[36,12,12,12,.25])[0]
 target=dict(source='fixture',track='1',box=box.tolist(),velocity=[0.,0.],velocity_valid=True,refs=['fixture'])
 ours=rasterize_pf([target],[],np.eye(3),future_times=[.2,.4],time_binding='geometry fixture only',decision_time=0.)['P'][0]
 a=official>=128;b=ours>0;intersection=(a&b).sum();union=(a|b).sum();iou=float(intersection/union)
 centroid_error=float(np.linalg.norm(np.argwhere(a).mean(0)-np.argwhere(b).mean(0)))
 assert official.shape==ours.shape==(192,96) and iou>.8 and centroid_error<1.
 records.append(dict(box=box.tolist(),iou_thresholded=iou,centroid_error_pixels=centroid_error))
result=dict(scope='original rasterizer geometry check only; no detector/MTR/planner evaluation',source=str(source),grid_checks=records,bitwise_equivalent=False,reason='binary pixel-centre mask versus upstream matplotlib antialiasing and polygon edges')
(Path(__file__).parent/'upstream_grid_check.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
