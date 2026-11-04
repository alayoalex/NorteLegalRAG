import { useState } from "react";

import { ApiError, askQuestion } from "./api";
import { Chat } from "./components/Chat";
import { DocumentsPanel, useDocuments } from "./components/DocumentsPanel";
import { Icon, NorthMark } from "./components/Icon";
import { Sidebar } from "./components/Sidebar";
import { newId, useConversations } from "./conversations";
import type { Turn } from "./conversations";

type Drawer = "history" | "documents" | null;

export function App() {
  const { conversations, addTurn, removeConversation } = useConversations();
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
