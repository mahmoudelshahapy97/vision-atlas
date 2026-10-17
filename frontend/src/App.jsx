import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toast";
import AppRouter from "./routes/AppRouter";

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <AppRouter />
      </ToastProvider>
    </AuthProvider>
  );
}
