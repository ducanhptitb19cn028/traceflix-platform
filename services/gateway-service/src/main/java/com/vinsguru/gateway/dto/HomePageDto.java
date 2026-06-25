package com.vinsguru.gateway.dto;

import com.fasterxml.jackson.databind.JsonNode;

/**
 * Aggregated home page. The downstream payloads (user profile+recs, trending
 * search hits, the featured movie) are carried as JSON so the gateway need not
 * duplicate every downstream DTO -- it composes, it does not own.
 */
public record HomePageDto(Integer userId,
                          JsonNode user,
                          JsonNode trending,
                          JsonNode featured) {
}
