package com.vinsguru.catalog.controller;

import com.vinsguru.catalog.dto.TitleDto;
import com.vinsguru.catalog.service.CatalogService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class CatalogController {

    private static final Logger log = LoggerFactory.getLogger(CatalogController.class);

    private final CatalogService catalogService;

    public CatalogController(CatalogService catalogService) {
        this.catalogService = catalogService;
    }

    @GetMapping("/api/catalog")
    public List<TitleDto> all() {
        log.info("catalog listing requested");
        return this.catalogService.listAll();
    }

    @GetMapping("/api/catalog/search")
    public List<TitleDto> search(@RequestParam(defaultValue = "") String q) {
        log.info("catalog search q={}", q);
        return this.catalogService.search(q);
    }

    @GetMapping("/api/catalog/{id}")
    public ResponseEntity<TitleDto> byId(@PathVariable Integer id) {
        return this.catalogService.getTitle(id)
                                  .map(ResponseEntity::ok)
                                  .orElseGet(() -> ResponseEntity.notFound().build());
    }

}
