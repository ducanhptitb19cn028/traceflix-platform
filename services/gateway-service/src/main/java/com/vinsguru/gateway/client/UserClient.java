package com.vinsguru.gateway.client;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.client.RestClient;

public class UserClient {

    private final RestClient restClient;

    public UserClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public JsonNode getUser(Integer userId) {
        return this.restClient.get()
                              .uri("/api/users/{id}", userId)
                              .retrieve()
                              .body(JsonNode.class);
    }

}
