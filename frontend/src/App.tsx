import { AuthProvider } from "./auth/AuthContext";
import AppRouter from "./router";

export default function App() {
  return (
    <AuthProvider>
      <AppRouter />
    </AuthProvider>
  );
}
