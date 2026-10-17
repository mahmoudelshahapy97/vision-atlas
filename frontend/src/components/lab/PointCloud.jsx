import { useEffect, useRef } from "react";

/** Drag to rotate, scroll to zoom. points = {xyz: [[x,y,z]...], rgb: [[r,g,b]...]} */
export default function PointCloud({ points }) {
  const canvas = useRef(null);
  const state = useRef({ yaw: 0.6, pitch: -0.25, zoom: 1, drag: null });

  useEffect(() => {
    const c = canvas.current;
    const ctx = c.getContext("2d");
    const xyz = points.xyz;
    const rgb = points.rgb;
    const span = Math.max(...xyz.flat().map(Math.abs)) || 1;

    function draw() {
      const { yaw, pitch, zoom } = state.current;
      const w = (c.width = c.clientWidth * devicePixelRatio);
      const h = (c.height = c.clientHeight * devicePixelRatio);
      ctx.fillStyle = getComputedStyle(c).getPropertyValue("--pc-bg") || "#16191d";
      ctx.fillRect(0, 0, w, h);
      const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
      const proj = xyz.map(([x, y, z], i) => {
        const x1 = cy * x + sy * z;
        const z1 = -sy * x + cy * z;
        const y2 = cp * y - sp * z1;
        const z2 = sp * y + cp * z1;
        const d = 3 * span - z2;
        const s = ((Math.min(w, h) * 0.9) / d) * zoom;
        return [w / 2 + x1 * s, h / 2 + y2 * s, d, i];
      });
      proj.sort((a, b) => b[2] - a[2]);
      const r = Math.max(1.5, 2.2 * devicePixelRatio);
      for (const [u, v, , i] of proj) {
        ctx.fillStyle = `rgb(${rgb[i][0]},${rgb[i][1]},${rgb[i][2]})`;
        ctx.fillRect(u - r / 2, v - r / 2, r, r);
      }
    }
    draw();
    const down = (e) => { state.current.drag = [e.clientX, e.clientY]; c.setPointerCapture(e.pointerId); };
    const move = (e) => {
      const d = state.current.drag;
      if (!d) return;
      state.current.yaw += (e.clientX - d[0]) * 0.01;
      state.current.pitch = Math.max(-1.5, Math.min(1.5, state.current.pitch + (e.clientY - d[1]) * 0.01));
      state.current.drag = [e.clientX, e.clientY];
      draw();
    };
    const up = () => { state.current.drag = null; };
    const wheel = (e) => { e.preventDefault(); state.current.zoom = Math.max(0.3, Math.min(5, state.current.zoom * (e.deltaY < 0 ? 1.1 : 0.9))); draw(); };
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    c.addEventListener("wheel", wheel, { passive: false });
    const ro = new ResizeObserver(draw);
    ro.observe(c);
    return () => {
      c.removeEventListener("pointerdown", down);
      c.removeEventListener("pointermove", move);
      c.removeEventListener("pointerup", up);
      c.removeEventListener("wheel", wheel);
      ro.disconnect();
    };
  }, [points]);

  return (
    <figure className="pointcloud">
      <canvas ref={canvas} aria-label="3D point cloud, drag to rotate" />
      <figcaption>{points.xyz.length.toLocaleString()} points · drag to rotate, scroll to zoom</figcaption>
    </figure>
  );
}
