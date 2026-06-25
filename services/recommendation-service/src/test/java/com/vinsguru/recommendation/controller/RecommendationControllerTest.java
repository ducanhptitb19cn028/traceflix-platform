package com.vinsguru.recommendation.controller;

import com.vinsguru.recommendation.dto.TitleDto;
import com.vinsguru.recommendation.service.RecommendationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(RecommendationController.class)
class RecommendationControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private RecommendationService recommendationService;

    @Test
    void recommend_returnsTitlesForUser() throws Exception {
        when(recommendationService.recommend(2)).thenReturn(List.of(
                new TitleDto(2, "The Godfather", "Crime", 1972, 9.2),
                new TitleDto(1, "The Shawshank Redemption", "Drama", 1994, 9.3)));

        mockMvc.perform(get("/api/recommendations").param("userId", "2"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$[0].name").value("The Godfather"))
               .andExpect(jsonPath("$.length()").value(2));
    }

    @Test
    void recommend_defaultsUserIdWhenAbsent() throws Exception {
        when(recommendationService.recommend(1)).thenReturn(List.of());

        mockMvc.perform(get("/api/recommendations"))
               .andExpect(status().isOk());
    }

}
