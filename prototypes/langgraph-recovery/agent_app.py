"""PROTOTYPE Agent Server entrypoint. The server injects its own checkpointer."""

from prototype.graph_app import build_server_graph

graph = build_server_graph()
