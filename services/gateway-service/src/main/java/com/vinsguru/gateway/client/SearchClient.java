package com.vinsguru.gateway.client;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.client.RestClient;

public class SearchClient {

    private final RestClient restClient;

    public SearchClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public JsonNode search(String query) {
        return this.restClient.get()
                              .uri(b -> b.path("/api/search").queryParam("q", query).build())
                              .retrieve()
                              .body(JsonNode.class);
    }

}
