import os
import json
import time
import numpy as np
import onnxruntime as ort

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSE_ONNX = os.path.join(BASE_DIR, "onnx", "yolo11n-pose.onnx")
FALL_ONNX = os.path.join(BASE_DIR, "onnx", "fall1dcnn.onnx")

def measure_onnx(onnx_path, dummy_input, n=50, warm=10):
    # 1. 순수 추론 시간 측정 (프로파일링 끄고 측정해야 정확함)
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(onnx_path, so, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name

    for _ in range(warm):
        sess.run(None, {in_name: dummy_input})

    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        sess.run(None, {in_name: dummy_input})
        times.append((time.perf_counter() - t0) * 1000)

    times = np.array(times)

    # 2. 커널 상세 프로파일링 (1회 실행)
    so_prof = ort.SessionOptions()
    so_prof.enable_profiling = True
    sess_prof = ort.InferenceSession(onnx_path, so_prof, providers=["CPUExecutionProvider"])
    sess_prof.run(None, {in_name: dummy_input})
    prof_file = sess_prof.end_profiling()

    with open(prof_file) as f:
        events = json.load(f)
    node_ev = [e for e in events if e.get("cat") == "Node" and e["name"].endswith("_kernel_time")]
    kernel_ms = sum(e["dur"] for e in node_ev) / 1000.0
    os.remove(prof_file)  # 생성된 임시 json 정리

    print(f"[{os.path.basename(onnx_path)}]")
    print(f"  - 실제 추론 ({n}회): mean={times.mean():.2f} ms | p95={np.percentile(times, 95):.2f} ms | {1000/times.mean():.1f} FPS")
    print(f"  - 커널 프로파일링: 노드 {len(node_ev)}개 | 합계 {kernel_ms:.2f} ms\n")

if __name__ == "__main__":
    dummy_yolo = np.random.rand(1, 3, 320, 320).astype(np.float32)
    dummy_fall = np.random.randn(1, 38, 10).astype(np.float32)

    measure_onnx(POSE_ONNX, dummy_yolo)
    measure_onnx(FALL_ONNX, dummy_fall)