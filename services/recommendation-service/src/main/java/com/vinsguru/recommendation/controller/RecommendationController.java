package com.vinsguru.recommendation.controller;

import com.vinsguru.recommendation.dto.TitleDto;
import com.vinsguru.recommendation.service.RecommendationService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class RecommendationController {

    private static final Logger log = LoggerFactory.getLogger(RecommendationController.class);

    private final RecommendationService recommendationService;

    public RecommendationController(RecommendationService recommendationService) {
        this.recommendationService = recommendationService;
    }

    @GetMapping("/api/recommendations")
    public List<TitleDto> recommend(@RequestParam(defaultValue = "1") Integer userId) {
        log.info("recommendations requested for user {}", userId);
        return this.recommendationService.recommend(userId);
    }

}
