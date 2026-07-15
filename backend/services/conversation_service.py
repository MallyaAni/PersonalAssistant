import uuid
import logging
from typing import AsyncGenerator, Dict, Any, List
from backend.core.interfaces import (
    MemoryService, 
    KnowledgeService, 
    InternetService, 
    NotificationService, 
    ToolService
)
from backend.agents.state import AgentState
from backend.agents.graph import assistant_graph

logger = logging.getLogger(__name__)

from typing import AsyncGenerator
from backend.core.interfaces import (
    MemoryService, 
    KnowledgeService, 
    InternetService, 
    NotificationService, 
    ToolService,
    ConversationRepository,
    ConversationContextBuilder,
    ConversationStreamer,
    ConversationTracer
)
from backend.agents.state import AgentState
from backend.agents.graph import assistant_graph

logger = logging.getLogger(__name__)

class ConversationService:
    def __init__(
        self,
        memory: MemoryService,
        knowledge: KnowledgeService,
        internet: InternetService,
        notifications: NotificationService,
        tools: ToolService,
        repository: ConversationRepository,
        context_builder: ConversationContextBuilder,
        streamer: ConversationStreamer,
        tracer: ConversationTracer
    ):
        self.memory = memory
        self.knowledge = knowledge
        self.internet = internet
        self.notifications = notifications
        self.tools = tools
        self.repository = repository
        self.context_builder = context_builder
        self.streamer = streamer
        self.tracer = tracer

    async def process_request(
        self, 
        user_id: str, 
        query: str
    ) -> AsyncGenerator[str, None]:
        trace_id = self.tracer.start_trace(user_id)
        logger.info(f"Started conversation trace: {trace_id} for user: {user_id}")

        # 1. Load context components
        profile = await self.memory.get_user_profile(user_id)
        episodic = await self.memory.get_episodic_memory(user_id, query)
        semantic = await self.memory.get_semantic_memory(query)

        # 2. Build Context and State
        context = self.context_builder.build_context(user_id, query)
        context.update({
            "profile": profile,
            "episodic": episodic,
            "semantic": semantic
        })

        initial_state = AgentState(
            user_id=user_id,
            current_query=query,
            history=[], # Would be loaded from repository in full implementation
            context_data=context,
            trace_id=trace_id
        )

        # 3. Execute AssistantGraph
        self.tracer.log_step(trace_id, "graph_execution", {"status": "started"})
        result = await assistant_graph.ainvoke(initial_state.model_dump())
        self.tracer.log_step(trace_id, "graph_execution", {"status": "completed"})
        
        response_text = result.get("messages", [{}])[0].get("content", "No response generated.")

        # 4. Persist conversation
        await self.repository.save_turn(initial_state.conversation_id, {
            "user_id": user_id,
            "query": query, 
            "response": response_text
        })

        # 5. Return streaming response via the streamer component
        yield f"Trace: {trace_id}\nResponse: {response_text}"
