import type { Conversation } from "../conversations";
import { Icon, NorthMark } from "./Icon";

type Props = {
  conversations: Conversation[];
  activeId: string;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
};

const dayFormat = new Intl.DateTimeFormat("es-ES", { day: "numeric", month: "short" });

function groupLabel(iso: string, now: Date): string {
  const date = new Date(iso);
  if (date.toDateString() === now.toDateString()) return "Hoy";
  const days = (now.getTime() - date.getTime()) / 86_400_000;
  return days < 7 ? "Esta semana" : "Anteriores";
}

export function Sidebar({ conversations, activeId, onNew, onSelect, onRemove }: Props) {
  const now = new Date();
  const groups = new Map<string, Conversation[]>();
  for (const conversation of conversations) {
    const label = groupLabel(conversation.updatedAt, now);
    groups.set(label, [...(groups.get(label) ?? []), conversation]);
  }

  return (
    <nav className="sidebar" aria-label="Conversaciones">
      <div className="brand">
        <NorthMark />
        <span>NorteLegal</span>
      </div>
      <button type="button" className="new-chat" onClick={onNew}>
        <Icon name="plus" />
        Nueva conversación
      </button>
      {conversations.length === 0 ? (
        <p className="sidebar-empty">Tus conversaciones aparecerán aquí.</p>
      ) : (
        [...groups].map(([label, items]) => (
          <div key={label} className="history-group">
            <h2 className="history-label">{label}</h2>
            <ul>
              {items.map((conversation) => (
                <li
                  key={conversation.id}
                  className={`history-item${conversation.id === activeId ? " history-item--active" : ""}`}
                >
                  <button
                    type="button"
                    className="history-open"
                    aria-current={conversation.id === activeId ? "page" : undefined}
                    onClick={() => onSelect(conversation.id)}
                  >
                    <span className="history-title">{conversation.title}</span>
                    {label === "Anteriores" && (
                      <span className="history-date">
                        {dayFormat.format(new Date(conversation.updatedAt))}
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    className="icon-button history-remove"
                    aria-label={`Eliminar la conversación «${conversation.title}»`}
                    title="Eliminar conversación"
                    onClick={() => {
                      if (window.confirm("¿Eliminar esta conversación de este navegador?")) {
                        onRemove(conversation.id);
                      }
                    }}
                  >
                    <Icon name="trash" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      <p className="sidebar-note">El historial se guarda solo en este navegador.</p>
    </nav>
  );
}
