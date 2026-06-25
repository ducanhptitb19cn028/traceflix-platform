package com.vinsguru.mesh.controller;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Generic fan-out endpoint. On each request it calls every downstream listed in
 * DOWNSTREAM_URLS (full target URLs, comma-separated) and returns a summary. A
 * downstream failure is caught and counted rather than re-thrown, so an upstream
 * caller shows the *latency* of waiting on a slow/dead dependency without itself
 * originating a new server error -- mirroring the synthetic model where only the
 * true root carries originating error spans and ancestors merely inherit latency.
 */
@RestController
public class MeshController {

    private static final Logger log = LoggerFactory.getLogger(MeshController.class);

    private final List<String> urls;
    private final List<RestClient> clients = new ArrayList<>();

    public MeshController(@Value("${downstream.urls:}") String csv) {
        this.urls = csv == null || csv.isBlank()
                ? List.of()
                : Arrays.stream(csv.split(",")).map(String::trim)
                        .filter(s -> !s.isEmpty()).toList();
        for (String u : urls) {
            this.clients.add(RestClient.create(u));
        }
    }

    @GetMapping({"/api/call", "/"})
    public ResponseEntity<Map<String, Object>> call(@RequestHeader Map<String, String> headers) {
        log.info("received headers: {}", headers);
        int ok = 0;
        int failed = 0;
        for (RestClient client : clients) {
            try {
                client.get().retrieve().toBodilessEntity();
                ok++;
            } catch (Exception e) {
                failed++;
                log.warn("downstream call failed: {}", e.getMessage());
            }
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("downstreams", urls.size());
        body.put("ok", ok);
        body.put("failed", failed);
        return ResponseEntity.ok(body);
    }

}
