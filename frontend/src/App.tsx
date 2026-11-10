import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { ApiError, ME_QUERY_KEY, askQuestion, getMe, logout, onUnauthenticated } from "./api";
import type { Me } from "./api";
import { Account } from "./components/Account";
import { AuthScreen } from "./components/AuthScreen";
import { Chat } from "./components/Chat";
import { DocumentsPanel, useDocuments } from "./components/DocumentsPanel";
import { Icon, NorthMark } from "./components/Icon";
import { Sidebar } from "./components/Sidebar";
import { newId, useConversations } from "./conversations";
import type { Turn } from "./conversations";
import { apiErrorMessage, errorMessage } from "./messages";

type Drawer = "history" | "documents" | null;

/** Decide entre la pantalla de acceso y el espacio de trabajo de la organización activa. */
export function App() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ME_QUERY_KEY, queryFn: getMe, staleTime: Infinity });
  const [notice, setNotice] = useState<string | null>(null);

  // Al cambiar de usuario o de organización se descarta el resto de la caché: los documentos de
  // una organización no deben verse ni un instante en otra. `me` se conserva y se actualiza: si se
  // borrara, esta pantalla seguiría observando la query eliminada.
  const enter = useCallback(
    (next: Me | null) => {
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== ME_QUERY_KEY[0] });
      queryClient.setQueryData(ME_QUERY_KEY, next);
    },
    [queryClient],
  );

  useEffect(
    () =>
      onUnauthenticated(() => {
        // Sin sesión conocida (la comprobación inicial de `getMe`) no hay nada que cerrar.
        if (!queryClient.getQueryData(ME_QUERY_KEY)) return;
        setNotice(errorMessage("unauthenticated"));
        enter(null);
      }),
    [queryClient, enter],
  );

  async function signOut() {
    try {
      await logout();
    } finally {
      setNotice(null);
      enter(null);
    }
  }

  if (me.isPending) return <main className="auth" aria-busy="true" />;
  if (me.isError) {
    return (
      <main className="auth">
        <p role="alert" className="alert">
          {apiErrorMessage(me.error)}{" "}
          <button type="button" className="text-button" onClick={() => void me.refetch()}>
            Reintentar
          </button>
        </p>
      </main>
    );
  }
  if (me.data === null) {
    return (
      <AuthScreen
        notice={notice}
        onSignedIn={(next) => {
          setNotice(null);
          enter(next);
        }}
      />
    );
  }
  // La clave vuelve a montar el espacio de trabajo, con su propio historial, al cambiar de
  // usuario o de organización.
  return (
    <Workspace
      key={`${me.data.user_id}:${me.data.organization.id}`}
      me={me.data}
      onSwitched={enter}
      onLogout={() => void signOut()}
    />
  );
}

type WorkspaceProps = {
  me: Me;
  onSwitched: (me: Me) => void;
  onLogout: () => void;
};

function Workspace({ me, onSwitched, onLogout }: WorkspaceProps) {
  const { conversations, addTurn, removeConversation } = useConversations(
    me.user_id,
    me.organization.id,
  );
  const [activeId, setActiveId] = useState(newId);
  // Preguntas en curso por conversación. La respuesta se guarda en la conversación donde se hizo
  // la pregunta aunque, mientras tanto, se haya abierto otra.
  const [pending, setPending] = useState<Record<string, string>>({});
  // En pantallas estrechas los paneles laterales se abren como cajones.
  const [drawer, setDrawer] = useState<Drawer>(null);
  const documents = useDocuments();

  const active = conversations.find((conversation) => conversation.id === activeId) ?? null;
  const readyDocuments = (documents.data ?? []).filter((d) => d.current_version !== null).length;

  async function ask(conversationId: string, question: string) {
    setPending((previous) => ({ ...previous, [conversationId]: question }));
    const turn: Turn = {
      id: newId(),
      question,
      askedAt: new Date().toISOString(),
      result: null,
      error: null,
    };
    try {
      turn.result = await askQuestion(question);
    } catch (error) {
      turn.error =
        error instanceof ApiError
          ? { code: error.code, correlationId: error.correlationId }
          : { code: "unexpected", correlationId: null };
    }
    addTurn(conversationId, turn);
    setPending(({ [conversationId]: _, ...rest }) => rest);
  }

  function open(id: string) {
    setActiveId(id);
    setDrawer(null);
  }

  return (
    <div
      className={`app${drawer ? ` app--${drawer}` : ""}`}
      onKeyDown={(event) => {
        if (event.key === "Escape") setDrawer(null);
      }}
    >
      <header className="topbar">
        <button
          type="button"
          className="icon-button"
          aria-label="Conversaciones"
          aria-expanded={drawer === "history"}
          onClick={() => setDrawer(drawer === "history" ? null : "history")}
        >
          <Icon name="history" />
        </button>
        <span className="brand">
          <NorthMark />
          <span>NorteLegal</span>
        </span>
        <button
          type="button"
          className="icon-button"
          aria-label="Documentos"
          aria-expanded={drawer === "documents"}
          onClick={() => setDrawer(drawer === "documents" ? null : "documents")}
        >
          <Icon name="documents" />
        </button>
      </header>

      <Sidebar
        conversations={conversations}
        activeId={activeId}
        onNew={() => open(newId())}
        onSelect={open}
        onRemove={(id) => {
          removeConversation(id);
          if (id === activeId) setActiveId(newId());
        }}
        footer={<Account me={me} onSwitched={onSwitched} onLogout={onLogout} />}
      />
      <main className="main">
        <Chat
          key={activeId}
          conversation={active}
          pendingQuestion={pending[activeId] ?? null}
          readyDocuments={readyDocuments}
          onAsk={(question) => void ask(activeId, question)}
        />
      </main>
      <DocumentsPanel />

      {drawer && (
        <button
          type="button"
          className="scrim"
          aria-label="Cerrar panel"
          onClick={() => setDrawer(null)}
        />
      )}
    </div>
  );
}
