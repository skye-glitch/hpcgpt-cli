-- Module file for the Delta HPC-GPT OpenCode AI coding agent CLI
local root = "/sw/external/opencode"
local version = "1.15.13"

help([[
Delta HPC-GPT OpenCode AI coding agent CLI

Usage:
  module load opencode/]] .. version .. [[

  opencode

Documentation: https://opencode.ai/docs
]])

whatis("Name: Delta OpenCode")
whatis("Version: " .. version)
whatis("Description: Delta HPC-GPT OpenCode AI coding agent CLI")
whatis("URL: https://opencode.ai")

prepend_path("PATH", pathJoin(root, "bin"))
setenv("OPENCODE_CONFIG", pathJoin(root, "delta-opencode.json")) -- Set this to your own config file
setenv("NCSA_LLM_URL", "https://example.endpoint/v1") -- Set this to your own hosted model URL