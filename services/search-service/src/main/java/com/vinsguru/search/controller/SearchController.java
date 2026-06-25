package com.vinsguru.search.controller;

import com.vinsguru.search.dto.TitleDto;
import com.vinsguru.search.service.SearchService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class SearchController {

    private static final Logger log = LoggerFactory.getLogger(SearchController.class);

    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    @GetMapping("/api/search")
    public List<TitleDto> search(@RequestParam(defaultValue = "") String q) {
        log.info("search requested q={}", q);
        return this.searchService.search(q);
    }

}
