# Changelog

## [0.8.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.7.0...v0.8.0) (2026-05-08)


### Features

* add analyze_current_pump_contributions tool to suggest ingredient replacements ([6fe2fff](https://github.com/rizz360/CocktailPi-MCP/commit/6fe2fffd4b00b286962fcd6002ee0b20fd7f8328))

## [0.7.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.6.0...v0.7.0) (2026-05-08)


### Features

* add set ingredient in bar functionality for individual and bulk updates ([a1b75b1](https://github.com/rizz360/CocktailPi-MCP/commit/a1b75b1384619e22e2b137678057a43f1a806005))
* enhance optimal pump configuration suggestion with candidate filtering and ranking ([8e0d928](https://github.com/rizz360/CocktailPi-MCP/commit/8e0d9281db7f2465db151f65b211186c16badf90))

## [0.6.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.5.1...v0.6.0) (2026-05-08)


### Features

* add analyze_pump_ingredient_optimization tool for recipe automation analysis ([3979835](https://github.com/rizz360/CocktailPi-MCP/commit/39798354e346c4e55ab9d68b3ede2e419164ec1f))
* add optimized pump configuration suggestion and ingredient evaluation logic ([0a71679](https://github.com/rizz360/CocktailPi-MCP/commit/0a7167918c1e6051a26448da47eaba7d21728697))
* enhance ingredient group ID collection to support ancestor expansion ([e76819c](https://github.com/rizz360/CocktailPi-MCP/commit/e76819c04f92aa40f586084a4ec0f9635ade2524))
* enhance pump ingredient optimization with new matching logic and ingredient type handling ([d0fa000](https://github.com/rizz360/CocktailPi-MCP/commit/d0fa0005f9a7f7024ef65e4fbd6d541441d3c507))
* improve step ingredient group ID extraction for explicit group requirements ([db088be](https://github.com/rizz360/CocktailPi-MCP/commit/db088bef92de2db29ccfc63eeab221245b958df3))
* refine step ingredient group ID extraction for explicit group requirements ([d545e66](https://github.com/rizz360/CocktailPi-MCP/commit/d545e662ff4ef50b2dbb9a32d41e01929f8d6f55))

## [0.5.1](https://github.com/rizz360/CocktailPi-MCP/compare/v0.5.0...v0.5.1) (2026-05-08)


### Bug Fixes

* normalize recipe owner handling and detect override failures ([6d6ca53](https://github.com/rizz360/CocktailPi-MCP/commit/6d6ca5339b98b9606f3cb381f005727ec8f10026))

## [0.5.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.4.0...v0.5.0) (2026-05-08)


### Features

* add URL and SVG recipe image upload tools ([8243330](https://github.com/rizz360/CocktailPi-MCP/commit/8243330ca08439bdf93470761968e6cbae2468b0))


### Documentation

* update README for clarity on MCP server usage and configuration ([3de5470](https://github.com/rizz360/CocktailPi-MCP/commit/3de5470642cb1f4e5b043bfae3f5d2ad355abd35))

## [0.4.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.3.0...v0.4.0) (2026-05-08)


### Features

* add recipe image MCP operations ([4bcd997](https://github.com/rizz360/CocktailPi-MCP/commit/4bcd99794d6db3e6d1a698896e7e2d5b2c0d2391))
* enhance documentation with authentication and recipe guidelines ([4adc635](https://github.com/rizz360/CocktailPi-MCP/commit/4adc635d246fce8cad28e8c772be4e71305fb98b))


### Documentation

* remove SKILL.md and update README for streamlined documentation ([d2dfc82](https://github.com/rizz360/CocktailPi-MCP/commit/d2dfc82e049b1f03141bc6beeeb9019380dda9db))

## [0.3.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.2.0...v0.3.0) (2026-05-08)


### Features

* update README and Docker Compose to use published image from GHCR ([7f01a1f](https://github.com/rizz360/CocktailPi-MCP/commit/7f01a1f74489bab2bab20e293e70621b2471e59f))
* update workflows to set up QEMU and support multi-platform builds ([0495c3a](https://github.com/rizz360/CocktailPi-MCP/commit/0495c3ac9e6201ecee2cd2ef1c85c41e720119b9))


### Documentation

* add CONTRIBUTING.md and update README for local development setup ([419fff8](https://github.com/rizz360/CocktailPi-MCP/commit/419fff8841abf5ebb8e079e4448e9eeed89bf477))
* clarify MCP server usage instructions and update connection setup details ([fcc1099](https://github.com/rizz360/CocktailPi-MCP/commit/fcc10995e63d8c0e4a51dd9fdcacd17e4805fec4))
* update Claude configuration instructions with environment variables for credentials ([9c3269b](https://github.com/rizz360/CocktailPi-MCP/commit/9c3269bf6dc8c0e5f2ab16923f444a5a466f5a77))
* update README for improved quick start instructions and add advanced reference documentation ([64a0660](https://github.com/rizz360/CocktailPi-MCP/commit/64a0660d12ada1099ae65fcad12d1a5b2e4d12d7))

## [0.2.0](https://github.com/rizz360/CocktailPi-MCP/compare/v0.1.0...v0.2.0) (2026-05-08)


### Features

* add Docker Compose configuration for CocktailPi MCP service ([cd62df1](https://github.com/rizz360/CocktailPi-MCP/commit/cd62df17598bb86b7c064d96ca70580da52dd57e))
* add Docker Compose setup example to README ([de22b08](https://github.com/rizz360/CocktailPi-MCP/commit/de22b084039887c88390fde0f4c23f419b009b51))
* add recipe update and delete MCP tools ([d73f564](https://github.com/rizz360/CocktailPi-MCP/commit/d73f564ba535121c23368304646979aee03652db))
* add username and password support for auto-login in settings ([e58faeb](https://github.com/rizz360/CocktailPi-MCP/commit/e58faeb5e4a7e9b56bdf02aad55994defc13cd94))
* initial CocktailPi MCP server ([c90b5c6](https://github.com/rizz360/CocktailPi-MCP/commit/c90b5c6ad9c205158f467f1604eaf739b6ce82ee))

## Changelog

All notable changes to this project will be documented in this file.
