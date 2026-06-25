package com.vinsguru.catalog.mapper;

import com.vinsguru.catalog.dto.TitleDto;
import com.vinsguru.catalog.entity.Title;

public class EntityDtoMapper {

    public static TitleDto toDto(Title title) {
        return new TitleDto(
                title.getId(),
                title.getName(),
                title.getGenre(),
                title.getReleaseYear(),
                title.getRating()
        );
    }

}
