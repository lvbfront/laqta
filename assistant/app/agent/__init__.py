"""The assistant's conversation loop (spec §12).

The only package that talks to an LLM. Everything it decides is delegated:
rules to app/domain/, date resolution to app/assistant_domain/, side effects
to app/tools/.
"""
