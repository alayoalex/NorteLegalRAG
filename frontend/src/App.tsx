import { DocumentList } from "./components/DocumentList";
import { UploadForm } from "./components/UploadForm";

// La pantalla de preguntas llega en el hito M3.
export function App() {
  return (
    <main>
      <header>
        <h1>NorteLegal</h1>
        <p className="muted">Asistente de conocimiento para contratos y políticas.</p>
      </header>
      <UploadForm />
      <DocumentList />
    </main>
  );
}
