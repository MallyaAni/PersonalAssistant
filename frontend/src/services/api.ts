const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function* streamChat(userId: string, query: string) {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ 
      user_id: userId, 
      query: query,
      metadata: {} 
    }),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    console.error("Server Error Details:", errorData);
    throw new Error(`Server responded with ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("Failed to get reader from response");

  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    yield decoder.decode(value);
  }
}
