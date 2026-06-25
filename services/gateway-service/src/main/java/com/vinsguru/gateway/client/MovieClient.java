package com.vinsguru.gateway.client;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.web.client.RestClient;

public class MovieClient {

    private final RestClient restClient;

    public MovieClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public JsonNode getMovie(Integer movieId) {
        return this.restClient.get()
                              .uri("/api/movies/{id}", movieId)
                              .retrieve()
                              .body(JsonNode.class);
    }

}
