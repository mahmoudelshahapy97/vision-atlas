import { lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Loading } from "../components/DataStates";
// Not lazy: it opens over the catalog, which must stay on screen while it loads.
import ProjectDrawer from "../components/ProjectDrawer";
import AppLayout from "../layouts/AppLayout";
import AuthLayout from "../layouts/AuthLayout";
import RequireAuth from "./RequireAuth";

const Catalog = lazy(() => import("../pages/Catalog"));
const LabPage = lazy(() => import("../pages/lab/LabPage"));
const Models = lazy(() => import("../pages/Models"));
const RunList = lazy(() => import("../pages/runs/RunList"));
const RunDetail = lazy(() => import("../pages/runs/RunDetail"));
const Board = lazy(() => import("../pages/Board"));
const Login = lazy(() => import("../pages/Login"));
const ProjectList = lazy(() => import("../pages/admin/ProjectList"));
const ProjectForm = lazy(() => import("../pages/admin/ProjectForm"));
const Users = lazy(() => import("../pages/admin/Users"));
const NotFound = lazy(() => import("../pages/NotFound"));

export default function AppRouter({ mode, onToggleMode }) {
  const { ready } = useAuth();
  if (!ready) return <Loading />;

  return (
    <BrowserRouter>
      {/* Each layout has its own Suspense around its Outlet. */}
      <Routes>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<Login mode="login" />} />
          <Route path="/register" element={<Login mode="register" />} />
        </Route>

        <Route element={<AppLayout mode={mode} onToggleMode={onToggleMode} />}>
          <Route path="/" element={<Catalog />}>
            <Route path="projects/:id" element={<ProjectDrawer />} />
          </Route>
          <Route path="/projects/:id/lab" element={<LabPage />} />
          <Route path="/models" element={<Models />} />
          <Route path="/runs">
            <Route index element={<RequireAuth><RunList /></RequireAuth>} />
            <Route path=":publicId" element={<RequireAuth><RunDetail /></RequireAuth>} />
          </Route>
          <Route path="/board" element={<RequireAuth><Board /></RequireAuth>} />

          <Route path="/admin">
            <Route index element={<RequireAuth minimum="admin"><ProjectList /></RequireAuth>} />
            <Route path="new" element={<RequireAuth minimum="admin"><ProjectForm /></RequireAuth>} />
            <Route path=":id/edit" element={<RequireAuth minimum="admin"><ProjectForm /></RequireAuth>} />
          </Route>
          <Route path="/users" element={<RequireAuth minimum="admin"><Users /></RequireAuth>} />

          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
