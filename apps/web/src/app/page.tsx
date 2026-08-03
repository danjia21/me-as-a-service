import { ChatWorkspace } from "./chat-workspace";
import { loadPublicInstance } from "../instance";

export const dynamic = "force-dynamic";

export default function Home() {
  return <ChatWorkspace instance={loadPublicInstance()} />;
}
